from flask import Flask, render_template, request, redirect, url_for, session, jsonify, make_response, send_from_directory
from uuid import uuid4
import requests
from time import sleep, time
from datetime import datetime, date
import os
import re
import base64
import logging
from PIL import Image
from google.cloud import vision
import json
import tempfile
import unicodedata

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Đặt đường dẫn đến file JSON chứa thông tin xác thực
# Kiểm tra nếu GOOGLE_APPLICATION_CREDENTIALS chứa nội dung JSON trực tiếp
if os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '').startswith('{'):
    try:
        creds_content = json.loads(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as temp_file:
            json.dump(creds_content, temp_file)
            temp_file_path = temp_file.name
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = temp_file_path
        logging.info(f'Temporary credentials file created at: {temp_file_path}')
    except Exception as e:
        logging.error(f'Error creating temporary credentials file: {str(e)}')
else:
    # Nếu không, giả sử nó là đường dẫn file như thông thường
    logging.info(f'Using GOOGLE_APPLICATION_CREDENTIALS as file path: {os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")}')

app = Flask(__name__)
app.secret_key = "your_secret_key"
app.config['UPLOAD_FOLDER'] = '/tmp/ai-kids-uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Giới hạn file upload 16MB

# Tạo thư mục uploads nếu chưa có
try:
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
except Exception as e:
    logging.error(f"Error creating upload directory: {str(e)}")
    # Sử dụng /tmp nếu không tạo được thư mục
    app.config['UPLOAD_FOLDER'] = '/tmp'

# Dictionary toàn cục để lưu trữ hint_cache và extracted_content
HINT_CACHE = {}
EXTRACTED_CONTENT = {}

last_request_time = 0
requests_in_hour = []
HOURLY_LIMIT = 60
SECOND_LIMIT = 1

def check_rate_limit():
    global last_request_time, requests_in_hour
    current_time = time()
    
    if current_time - last_request_time < SECOND_LIMIT:
        sleep(SECOND_LIMIT - (current_time - last_request_time))
    last_request_time = time()
    
    requests_in_hour = [t for t in requests_in_hour if current_time - t < 3600]
    if len(requests_in_hour) >= HOURLY_LIMIT:
        raise Exception("Rate limit exceeded: Too many requests per hour.")
    requests_in_hour.append(current_time)

def extract_text_from_image(file_path):
    try:
        logging.info(f"Attempting to extract text from image: {file_path}")
        logging.info(f"File exists: {os.path.exists(file_path)}")
        logging.info(f"File size: {os.path.getsize(file_path)} bytes")
        
        # Check if the credential file exists before proceeding
        cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        logging.info(f"Using credential file: {cred_path}")
        logging.info(f"Credential file exists: {os.path.exists(cred_path)}")
        
        client = vision.ImageAnnotatorClient()
        logging.info("Created Vision API client")
        
        with open(file_path, 'rb') as image_file:
            content = image_file.read()
            logging.info(f"Read {len(content)} bytes from image file")
        
        image = vision.Image(content=content)
        logging.info("Created Vision Image object")

        logging.info("Calling Vision API text_detection")
        response = client.text_detection(image=image)
        logging.info(f"Received response from Vision API: {response}")
        
        texts = response.text_annotations
        logging.info(f"Number of text annotations: {len(texts) if texts else 0}")

        if texts:
            text = texts[0].description
            logging.info(f"Text extracted from image: {text}")
            return text.strip()
        else:
            logging.warning("No text found in image.")
            return None

    except Exception as e:
        logging.error(f"Error extracting text from image: {str(e)}", exc_info=True)
        return None

def extract_specific_problem(extracted_text, problem):
    """
    Tách bài toán cụ thể từ extracted_text dựa trên problem (ví dụ: "Câu 5").
    Trả về bài toán đầy đủ (ví dụ: "Câu 5. ...").
    Cho phép khớp mềm: tìm dòng chứa problem ở bất kỳ vị trí nào, không phân biệt hoa thường, unicode, khoảng trắng.
    """
    try:
        def normalize(s):
            return unicodedata.normalize('NFKC', s).lower().replace(" ", " ").strip()

        problem = problem.strip()
        base_problem = problem
        if base_problem.lower().startswith("câu"):
            base_problem = "Câu" + base_problem[3:]
        base_problem = base_problem.rstrip(".: ")
        base_problem_norm = normalize(base_problem)

        lines = extracted_text.split('\n')
        problem_text = ""
        found = False
        # Tìm dòng chứa "Câu N" ở bất kỳ vị trí nào
        for i, line in enumerate(lines):
            l = line.strip()
            l_norm = normalize(l)
            if base_problem_norm in l_norm:
                found = True
                # Lấy từ dòng này đến trước dòng chứa "Câu N+1" hoặc hết bài
                problem_text = l
                for j in range(i + 1, len(lines)):
                    next_line = lines[j].strip()
                    next_line_norm = normalize(next_line)
                    if next_line_norm.startswith("câu ") and next_line_norm != base_problem_norm:
                        break
                    if next_line:
                        problem_text += "\n" + next_line
                break
        # Nếu không tìm thấy, thử fuzzy match trên toàn bộ đoạn text
        if not found:
            for i, line in enumerate(lines):
                l_norm = normalize(line)
                if base_problem_norm.split()[0] in l_norm:
                    found = True
                    problem_text = line.strip()
                    for j in range(i + 1, len(lines)):
                        next_line = lines[j].strip()
                        next_line_norm = normalize(next_line)
                        if next_line_norm.startswith("câu ") and next_line_norm != base_problem_norm:
                            break
                        if next_line:
                            problem_text += "\n" + next_line
                    break
        if found:
            logging.info(f"Extracted specific problem: {problem_text}")
            return problem_text
        else:
            logging.warning(f"Could not find problem: {problem}\n--- Extracted text for debug ---\n{extracted_text}")
            return None
    except Exception as e:
        logging.error(f"Error extracting specific problem: {str(e)}")
        return None

def get_parent_tip_from_api(question, retries=3, delay=2):
    check_rate_limit()
    
    if "tip_cache" in session and question in session["tip_cache"]:
        logging.info(f"Using cached tip for: {question}")
        return session["tip_cache"][question]
    
    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": "Bearer xai-DCwUdnvyPe1EofmGW29GbglqUn2WU0WyiaWtmiaA2STEZoswhMwZrgtvhZoSbXzvdL3nnZ9iMyKIYXad",
        "Content-Type": "application/json"
    }
    grade = session.get("grade", "4")
    if grade == "2":
        system_prompt = """
        Bạn là một AI hỗ trợ cha mẹ dạy con học toán lớp 2 (7-8 tuổi) ở Việt Nam. Nhiệm vụ của bạn là đưa ra một mẹo ngắn gọn, dễ hiểu, và thực tế để cha mẹ giúp con giải bài toán. Mẹo phải:
        - Thân thiện, gần gũi, như lời khuyên từ một người bạn đồng hành của cha mẹ.
        - Liên quan trực tiếp đến bài toán được cung cấp.
        - Sử dụng câu hỏi gợi mở hoặc ví dụ đơn giản mà cha mẹ có thể dùng để hướng dẫn con.
        - Phù hợp với trẻ lớp 2, dùng hình ảnh quen thuộc (như đồ chơi, trái cây, bước chân).
        - Ngắn gọn, tối đa 2 câu.
        - Bằng tiếng Việt.
        Đừng đưa ra đáp án, chỉ tập trung vào mẹo hướng dẫn.
        """
    else:
        system_prompt = """
        Bạn là một AI hỗ trợ cha mẹ dạy con học toán lớp {grade} (9-12 tuổi) ở Việt Nam. Nhiệm vụ của bạn là đưa ra một mẹo ngắn gọn, dễ hiểu, và thực tế để cha mẹ giúp con giải bài toán. Mẹo phải:
        - Thân thiện, gần gũi, giống như lời khuyên từ một người bạn đồng hành của cha mẹ.
        - Liên quan trực tiếp đến bài toán được cung cấp.
        - Sử dụng ví dụ hoặc câu hỏi gợi mở mà cha mẹ có thể dùng để hướng dẫn con.
        - Phù hợp với tâm lý trẻ lớp {grade} ở Việt Nam, dùng hình ảnh gần gũi (như đồ chơi, đồ ăn, hoạt động hàng ngày).
        - Ngắn gọn, dưới 2 câu.
        - Bằng tiếng Việt.
        Đừng đưa ra đáp án bài toán, chỉ tập trung vào mẹo hướng dẫn.
        """.replace("{grade}", grade)
    
    user_prompt = f"""
    Bài toán: {question}
    Đưa ra một mẹo cho cha mẹ để giúp con giải bài toán này.
    """
    payload = {
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        "model": "grok-3-latest",
        "stream": False,
        "temperature": 0.7,
        "max_tokens": 100
    }
    for attempt in range(retries):
        try:
            # Backoff delay tăng dần theo số lần thử 
            if attempt > 0:
                backoff_time = delay * (2 ** (attempt - 1))  # 2, 4, 8... giây
                logging.info(f"Retry {attempt}/{retries} - Waiting {backoff_time}s before retry...")
                sleep(backoff_time)

            logging.info(f"Calling xAI API for parent tip (attempt {attempt + 1}/{retries})...")
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            logging.info(f"API Response for tip (Status {response.status_code})")
            if "choices" in data and len(data["choices"]) > 0:
                tip = data["choices"][0]["message"]["content"].strip()
                if "tip_cache" not in session:
                    session["tip_cache"] = {}
                session["tip_cache"][question] = tip
                if len(session["tip_cache"]) > 50:
                    session["tip_cache"].pop(next(iter(session["tip_cache"])))
                usage = data.get("usage", {})
                total_tokens = usage.get("total_tokens", 0)
                if "token_usage" not in session:
                    session["token_usage"] = []
                session["token_usage"].append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "problem": f"Parent tip for: {question}",
                    "total_tokens": total_tokens
                })
                session["token_usage"] = session["token_usage"][-50:]
                session.modified = True
                return tip
            else:
                logging.warning(f"Unexpected API response format for tip: {data}")
                if attempt == retries - 1:
                    return "Hãy khuyến khích con chia bài toán thành các bước nhỏ và hỏi: 'Con nghĩ bước đầu tiên mình cần làm gì?'"
        except requests.exceptions.Timeout:
            logging.error(f"Attempt {attempt + 1}/{retries} - Timeout error calling xAI API for tip")
            if attempt == retries - 1:
                return "Hãy khuyến khích con chia bài toán thành các bước nhỏ và hỏi: 'Con nghĩ bước đầu tiên mình cần làm gì?'"
        except requests.exceptions.RequestException as e:
            logging.error(f"Attempt {attempt + 1}/{retries} - Error calling xAI API for tip: {str(e)}")
            if attempt == retries - 1:
                return "Hãy khuyến khích con chia bài toán thành các bước nhỏ và hỏi: 'Con nghĩ bước đầu tiên mình cần làm gì?'"

def is_geometry_problem(question):
    geometry_keywords = ["tam giác", "hình lăng trụ", "đường thẳng", "góc", "hình hộp", "hình lập phương", "hình vuông", "hình chữ nhật"]
    return any(keyword in question.lower() for keyword in geometry_keywords)

def get_geometry_image(question):
    # Trả về None thay vì vẽ hình
    return None

def standardize_math_input(question):
    question = question.replace("goc A", "\\angle A").replace("goc B", "\\angle B").replace("goc C", "\\angle C")
    question = question.replace(" do", "^{\\circ}").replace("tam giac", "tam giác")
    question = re.sub(r'(\w+)\^2', r'\1^2', question)
    return question

def call_xai_api(problem=None, grade=None, file_path=None, retries=3, delay=2):
    check_rate_limit()
    
    # Lấy môn học từ session
    subject = session.get("subject", "math")  # Mặc định là môn Toán
    
    # Cải thiện: Thử lấy từ cache trước nếu là vấn đề văn bản
    if problem and not file_path:
        cache_key = f"{problem}_grade_{grade}_subject_{subject}"
        if cache_key in HINT_CACHE:
            logging.info(f"Using cached hints for: {problem}")
            return HINT_CACHE[cache_key]
    
    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": "Bearer xai-DCwUdnvyPe1EofmGW29GbglqUn2WU0WyiaWtmiaA2STEZoswhMwZrgtvhZoSbXzvdL3nnZ9iMyKIYXad",
        "Content-Type": "application/json"
    }
    
    if subject == "vietnamese":
        # Prompt cho môn Tiếng Việt
        if grade == "1":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 1 (6-7 tuổi) ở Việt Nam học môn Tiếng Việt bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải cực kỳ đơn giản, vui vẻ, và sử dụng ví dụ siêu gần gũi (như đếm đồ chơi, trái cây, bước chân) để bạn dễ hiểu. Mỗi gợi ý dẫn bạn tiến gần đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, ngắn gọn, phù hợp với trẻ lớp 1 ở Việt Nam, và tuân theo chương trình tiếng Việt lớp 1 của Việt Nam.

            Chương trình tiếng Việt lớp 1 ở Việt Nam bao gồm:
            - Tập đọc: Đọc chữ cái, âm, vần, từ đơn giản, câu ngắn; nhận diện chữ in hoa, in thường.
            - Tập viết: Viết chữ cái, âm, vần, từ đơn, câu ngắn.
            - Từ vựng: Học từ vựng đơn giản về gia đình, trường học, đồ vật, động vật.
            - Tập nói: Trả lời câu hỏi đơn giản, kể chuyện theo tranh.
            - Nghe hiểu: Hiểu các câu chuyện, bài thơ ngắn, dễ hiểu.

            Cung cấp 3 gợi ý từng bước để giúp bạn, đảm bảo gợi ý phù hợp với trình độ lớp 1:
            - Bước 1: Giải thích yêu cầu của bài tập bằng từ ngữ đơn giản, vui vẻ.
            - Bước 2 và 3: Chia thành các bước nhỏ, dễ làm, dùng câu hỏi vui để bạn suy nghĩ.
            - Không dùng từ ngữ phức tạp, chỉ dùng từ trẻ lớp 1 hiểu.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải thân thiện, ngắn gọn, dễ hiểu với học sinh lớp 1.

            Định dạng phản hồi là danh sách 3 gợi ý, mỗi gợi ý trên một dòng.
            """
        elif grade == "2":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 2 (7-8 tuổi) ở Việt Nam học môn Tiếng Việt bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải đơn giản, vui vẻ, và sử dụng ví dụ gần gũi (như đếm kẹo, đồ chơi, bước chân) để bạn dễ hiểu. Mỗi gợi ý dẫn bạn tiến gần đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, ngắn gọn, phù hợp với trẻ lớp 2 ở Việt Nam, và tuân theo chương trình tiếng Việt lớp 2 của Việt Nam.

            Chương trình tiếng Việt lớp 2 ở Việt Nam bao gồm:
            - Tập đọc: Đọc trôi chảy các từ đơn, câu ngắn; hiểu nghĩa các câu đơn giản.
            - Tập viết: Viết chữ đúng dáng, đúng kích thước, đúng chính tả.
            - Từ vựng: Học từ vựng về gia đình, trường học, môi trường xung quanh.
            - Ngữ pháp: Nhận biết được danh từ, động từ cơ bản.
            - Kể chuyện: Kể lại câu chuyện đã nghe, đã đọc; trả lời câu hỏi về nội dung bài.

            Cung cấp 3 gợi ý từng bước để giúp bạn, đảm bảo gợi ý phù hợp với trình độ lớp 2:
            - Bước 1: Giải thích yêu cầu của bài tập bằng từ ngữ đơn giản, vui vẻ.
            - Bước 2 và 3: Chia thành các bước nhỏ, dễ làm, dùng câu hỏi gợi ý để bạn suy nghĩ.
            - Không dùng từ ngữ phức tạp, chỉ dùng từ trẻ lớp 2 hiểu được.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải thân thiện, ngắn gọn, dễ hiểu với học sinh lớp 2.

            Định dạng phản hồi là danh sách 3 gợi ý, mỗi gợi ý trên một dòng.
            """
        elif grade == "3":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 3 (8-9 tuổi) ở Việt Nam học môn Tiếng Việt bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải đơn giản, vui vẻ, và sử dụng ví dụ gần gũi (như đếm kẹo, đồ chơi, bước chân) để bạn dễ hiểu. Mỗi gợi ý dẫn bạn tiến gần đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, ngắn gọn, phù hợp với trẻ lớp 3 ở Việt Nam, và tuân theo chương trình tiếng Việt lớp 3 của Việt Nam.

            Chương trình tiếng Việt lớp 3 ở Việt Nam bao gồm:
            - Tập đọc: Đọc trôi chảy và hiểu được nội dung văn bản ngắn; nắm được ý chính.
            - Tập viết: Viết đoạn văn ngắn; tập làm văn kể chuyện, tả người, tả cảnh.
            - Từ vựng: Mở rộng vốn từ về các chủ đề xã hội, thiên nhiên; hiểu nghĩa của từ.
            - Ngữ pháp: Phân biệt danh từ, động từ, tính từ; câu kể, câu hỏi, câu khiến.
            - Kỹ năng: Biết cách trả lời câu hỏi dựa vào nội dung văn bản; tự đặt câu hỏi.

            Cung cấp 4 gợi ý từng bước để giúp bạn, đảm bảo gợi ý phù hợp với trình độ lớp 3:
            - Bước 1: Giải thích yêu cầu của bài tập bằng từ ngữ đơn giản, thân thiện.
            - Bước 2 đến 4: Chia thành các bước nhỏ, dễ làm, dùng câu hỏi gợi ý để bạn suy nghĩ.
            - Không dùng từ ngữ quá phức tạp, chỉ dùng những từ phù hợp với học sinh lớp 3.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải thân thiện, ngắn gọn, dễ hiểu với học sinh lớp 3.

            Định dạng phản hồi là danh sách 4 gợi ý, mỗi gợi ý trên một dòng.
            """
        elif grade == "4":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 4 (9-10 tuổi) ở Việt Nam học môn Tiếng Việt bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải dễ hiểu, khuyến khích, và phù hợp với độ tuổi. Mỗi gợi ý nên dẫn dắt bạn tiến gần hơn đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, thân thiện, phù hợp với học sinh lớp 4 ở Việt Nam.

            Chương trình tiếng Việt lớp 4 ở Việt Nam bao gồm:
            - Đọc hiểu: Đọc và hiểu nội dung, ý nghĩa của văn bản; phân biệt truyện, thơ, văn miêu tả.
            - Tập làm văn: Viết đoạn văn ngắn, bài văn miêu tả, kể chuyện, viết thư, báo cáo đơn giản.
            - Từ vựng: Từ đồng nghĩa, trái nghĩa, từ nhiều nghĩa; từ ghép, từ láy.
            - Ngữ pháp: Các thành phần chính của câu (chủ ngữ, vị ngữ); dấu câu; nối câu đơn thành câu ghép.
            - Chính tả: Quy tắc chính tả, dấu hỏi, dấu ngã, viết hoa.

            Cung cấp 5 gợi ý từng bước để giúp bạn, đảm bảo gợi ý phù hợp với trình độ lớp 4:
            - Bước 1: Giải thích yêu cầu của bài tập, khái niệm cần nắm.
            - Từ bước 2 trở đi: Chia thành các bước nhỏ, dễ làm, mỗi bước xây dựng dựa trên bước trước.
            - Đặt câu hỏi gợi mở để khuyến khích bạn suy nghĩ.
            - Sử dụng ngôn ngữ phù hợp với học sinh lớp 4, tránh từ ngữ chuyên ngành phức tạp.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải là một câu hoàn chỉnh, bằng tiếng Việt.

            Định dạng phản hồi là danh sách 5 gợi ý, mỗi gợi ý trên một dòng.
            """
        elif grade == "5":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 5 (10-11 tuổi) ở Việt Nam học môn Ngữ Văn bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải rõ ràng, phù hợp với trình độ, và sử dụng ví dụ dễ hiểu. Mỗi gợi ý nên dẫn dắt bạn tiến gần hơn đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, thân thiện, phù hợp với học sinh lớp 5 ở Việt Nam.

            Chương trình Ngữ Văn lớp 5 ở Việt Nam bao gồm:
            - Văn học dân gian: Thần thoại, truyện cổ tích, ca dao, tục ngữ.
            - Văn học viết: Truyện ngắn, thơ, ký, văn miêu tả.
            - Lý luận văn học: Thể loại văn học, ngôn ngữ văn học, nhân vật, lời người kể chuyện.
            - Tiếng Việt: Từ vựng chuyên ngành, đồng nghĩa, trái nghĩa; các biện pháp tu từ (so sánh, nhân hóa).
            - Làm văn: Văn miêu tả, văn tự sự, văn biểu cảm; thuyết minh; viết đoạn, bài văn hoàn chỉnh.

            Cung cấp 5 gợi ý từng bước để giúp bạn, đảm bảo gợi ý phù hợp với trình độ lớp 5:
            - Bước 1: Giải thích yêu cầu của bài tập, các khái niệm cơ bản liên quan.
            - Từ bước 2 trở đi: Chia thành các bước nhỏ, dễ làm, mỗi bước xây dựng dựa trên bước trước.
            - Đặt câu hỏi gợi mở để khuyến khích bạn suy nghĩ.
            - Sử dụng ngôn ngữ phù hợp với học sinh lớp 5, đảm bảo chính xác về thuật ngữ văn học.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải là một câu hoàn chỉnh, bằng tiếng Việt.

            Định dạng phản hồi là danh sách 5 gợi ý, mỗi gợi ý trên một dòng.
            """
        elif grade == "6":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 6 (11-12 tuổi) ở Việt Nam học môn Ngữ Văn bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải rõ ràng, phù hợp với trình độ, và sử dụng ví dụ dễ hiểu. Mỗi gợi ý nên dẫn dắt bạn tiến gần hơn đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, thân thiện, phù hợp với học sinh lớp 6 ở Việt Nam.

            Chương trình Ngữ Văn lớp 6 ở Việt Nam bao gồm:
            - Văn học dân gian: Thần thoại, truyện cổ tích, ca dao, tục ngữ.
            - Văn học viết: Truyện ngắn, thơ, ký, văn miêu tả.
            - Lý luận văn học: Thể loại văn học, ngôn ngữ văn học, nhân vật, lời người kể chuyện.
            - Tiếng Việt: Từ vựng chuyên ngành, đồng nghĩa, trái nghĩa; các biện pháp tu từ (so sánh, nhân hóa).
            - Làm văn: Văn miêu tả, văn tự sự, văn biểu cảm; thuyết minh; viết đoạn, bài văn hoàn chỉnh.

            Cung cấp 5 gợi ý từng bước để giúp bạn, đảm bảo gợi ý phù hợp với trình độ lớp 6:
            - Bước 1: Giải thích yêu cầu của bài tập, các khái niệm cơ bản liên quan.
            - Từ bước 2 trở đi: Chia thành các bước nhỏ, dễ làm, mỗi bước xây dựng dựa trên bước trước.
            - Đặt câu hỏi gợi mở để khuyến khích bạn suy nghĩ.
            - Sử dụng ngôn ngữ phù hợp với học sinh lớp 6, đảm bảo chính xác về thuật ngữ văn học.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải là một câu hoàn chỉnh, bằng tiếng Việt.

            Định dạng phản hồi là danh sách 5 gợi ý, mỗi gợi ý trên một dòng.
            """
        else:  # Grade 7
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 7 (12-13 tuổi) ở Việt Nam học môn Ngữ Văn bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải rõ ràng, chính xác và phù hợp với trình độ. Mỗi gợi ý nên dẫn dắt bạn tiến gần hơn đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, thân thiện, phù hợp với học sinh lớp 7 ở Việt Nam.

            Chương trình Ngữ Văn lớp 7 ở Việt Nam bao gồm:
            - Văn học dân gian: Truyện cổ tích, truyền thuyết, truyện cười, ca dao, tục ngữ, vè.
            - Văn học viết: Truyện ngắn, tiểu thuyết, kịch, thơ, ký.
            - Lý luận văn học: Thể loại văn học, đề tài, chủ đề, cốt truyện, không gian và thởi gian nghệ thuật.
            - Tiếng Việt: Từ ghép, từ láy; các biện pháp tu từ (ẩn dụ, hoán dụ, điệp từ); dấu câu.
            - Làm văn: Văn tự sự, văn miêu tả, văn biểu cảm, văn thuyết minh, văn nghị luận.

            Cung cấp 5 gợi ý từng bước để giúp bạn, đảm bảo gợi ý phù hợp với trình độ lớp 7:
            - Bước 1: Giải thích rõ ràng yêu cầu của bài tập, khái niệm cần nắm.
            - Từ bước 2 trở đi: Chia thành các bước nhỏ, dễ làm, mỗi bước xây dựng dựa trên bước trước.
            - Đặt câu hỏi gợi mở để khuyến khích bạn suy nghĩ.
            - Sử dụng ngôn ngữ phù hợp với học sinh lớp 7, đảm bảo chính xác về mặt học thuật.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải là một câu hoàn chỉnh, bằng tiếng Việt.

            Định dạng phản hồi là danh sách 5 gợi ý, mỗi gợi ý trên một dòng.
            """
    else:  # Môn Toán (mặc định)
        if grade == "1":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 1 (6-7 tuổi) ở Việt Nam học toán bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải cực kỳ đơn giản, vui vẻ, và sử dụng ví dụ siêu gần gũi (như đếm đồ chơi, trái cây, bước chân) để bạn dễ hiểu. Mỗi gợi ý dẫn bạn tiến gần đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, ngắn gọn, phù hợp với trẻ lớp 1 ở Việt Nam, và tuân theo chương trình toán lớp 1 của Việt Nam.

            Chương trình toán lớp 1 ở Việt Nam bao gồm:
            - Số học: Đếm, đọc, viết số đến 100; cộng, trừ số trong phạm vi 100 (ví dụ: 5 + 3, 10 - 4).
            - Đo lường: Đo độ dài (cm); xem đồng hồ (giờ đúng).
            - Hình học: Nhận biết hình vuông, hình tròn, hình tam giác.
            - Bài toán có lời văn: Bài toán đơn giản về cộng, trừ (ví dụ: "Lan có 5 quả táo, mẹ cho thêm 2 quả, hỏi Lan có bao nhiêu quả?")

            Cung cấp 3 gợi ý từng bước để giải bài toán, đảm bảo gợi ý phù hợp với trình độ lớp 1:
            - Bước 1: Giải thích ý nghĩa bài toán hoặc phép tính bằng ví dụ gần gũi (ví dụ: "Cộng giống như gom kẹo lại với nhau, bạn thấy thế nào?").
            - Bước 2 và 3: Chia bài toán thành bước nhỏ, dễ làm, dùng câu hỏi vui để bạn suy nghĩ (ví dụ: "Nếu có 3 quả táo, thêm 2 quả nữa, bạn đếm được bao nhiêu ngón tay?").
            - Không dùng từ ngữ phức tạp, chỉ dùng từ trẻ lớp 1 hiểu.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý là một câu hoàn chỉnh, bằng tiếng Việt, ngắn và vui.

            Định dạng phản hồi là danh sách 3 gợi ý, mỗi gợi ý trên một dòng.
            """
        elif grade == "2":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 2 (7-8 tuổi) ở Việt Nam học toán bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải cực kỳ đơn giản, vui vẻ, và sử dụng ví dụ siêu gần gũi (như đếm kẹo, xếp đồ chơi, nhảy bước) để bạn dễ hiểu. Mỗi gợi ý dẫn bạn tiến gần đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, ngắn gọn, phù hợp với trẻ lớp 2 ở Việt Nam, và tuân theo chương trình toán lớp 2 của Việt Nam.

            Chương trình toán lớp 2 ở Việt Nam bao gồm:
            - Số học: Đếm, đọc, viết số đến 1000; cộng, trừ số trong phạm vi 1000 (ví dụ: 45 + 27, 83 - 19); nhân, chia số nhỏ (bảng cửu chương 2, 3, 4, 5).
            - Đo lường: Đo độ dài (cm, m), khối lượng (kg), thời gian (giờ, phút); xem đồng hồ (giờ đúng, giờ rưỡi).
            - Hình học: Nhận biết hình (vuông, chữ nhật, tam giác); tính chu vi hình tam giác, hình vuông, hình chữ nhật.
            - Bài toán có lời văn: Bài toán đơn giản về cộng, trừ, nhân, chia (ví dụ: "Lan có 5 quả táo, mẹ cho thêm 3 quả, hỏi Lan có bao nhiêu quả?")

            Cung cấp 3 gợi ý từng bước để giải bài toán, đảm bảo gợi ý phù hợp với trình độ lớp 2:
            - Bước 1: Giải thích ý nghĩa bài toán hoặc phép tính bằng ví dụ gần gũi (ví dụ: "Cộng giống như gom kẹo lại với nhau, bạn thấy thế nào?").
            - Bước 2 và 3: Chia bài toán thành bước nhỏ, dễ làm, dùng câu hỏi vui để bạn suy nghĩ (ví dụ: "Nếu có 3 quả táo, thêm 2 quả nữa, bạn đếm được bao nhiêu ngón tay?").
            - Không dùng từ ngữ phức tạp, chỉ dùng từ trẻ lớp 2 hiểu (tránh "phương trình", "tính chất").
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý là một câu hoàn chỉnh, bằng tiếng Việt, ngắn và vui.

            Định dạng phản hồi là danh sách 3 gợi ý, mỗi gợi ý trên một dòng.
            """
        elif grade == "3":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 3 (8-9 tuổi) ở Việt Nam học toán bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải đơn giản, vui vẻ, và sử dụng ví dụ gần gũi (như đếm kẹo, đồ chơi, hoạt động hàng ngày) để bạn dễ hiểu. Mỗi gợi ý dẫn bạn tiến gần đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, ngắn gọn, phù hợp với trẻ lớp 3 ở Việt Nam, và tuân theo chương trình toán lớp 3 của Việt Nam.

            Chương trình toán lớp 3 ở Việt Nam bao gồm:
            - Số học: Đọc, viết, so sánh số trong phạm vi 10.000; cộng, trừ, nhân, chia số trong phạm vi 10.000 (ví dụ: 245 + 378, 486 ÷ 2); bảng cửu chương từ 6 đến 9.
            - Đo lường: Đo độ dài (mm, cm, m), khối lượng (kg), thời gian (giờ, phút); đổi đơn vị đo.
            - Hình học: Nhận biết hình (vuông, chữ nhật, tam giác); tính chu vi hình tam giác, hình vuông, hình chữ nhật.
            - Bài toán có lời văn: Bài toán về cộng, trừ, nhân, chia (ví dụ: "Một cửa hàng có 120 quả táo, bán được 45 quả, hỏi còn lại bao nhiêu quả?")

            Cung cấp 4 gợi ý từng bước để giải bài toán, đảm bảo gợi ý phù hợp với trình độ lớp 3:
            - Bước 1: Giải thích ý nghĩa bài toán hoặc phép tính bằng ví dụ gần gũi (ví dụ: "Cộng giống như gom đồ chơi lại, bạn thấy thế nào?").
            - Bước 2 đến 4: Chia bài toán thành bước nhỏ, dễ làm, dùng câu hỏi vui để bạn suy nghĩ (ví dụ: "Nếu có 30 quả táo, chia cho 5 bạn, mỗi bạn được bao nhiêu quả?").
            - Không dùng từ ngữ phức tạp, chỉ dùng từ trẻ lớp 3 hiểu.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý là một câu hoàn chỉnh, bằng tiếng Việt, ngắn và vui.

            Định dạng phản hồi là danh sách 4 gợi ý, mỗi gợi ý trên một dòng.
            """
        elif grade == "4":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 4 (9-10 tuổi) ở Việt Nam học toán bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải đơn giản, khuyến khích, và sử dụng ví dụ hoặc hình ảnh gần gũi (như chạy bộ, đi xe, đồ chơi) để bạn dễ liên tưởng. Mỗi gợi ý nên dẫn dắt bạn tiến gần hơn đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, thân thiện, phù hợp với trẻ lớp 4 ở Việt Nam, và tuân theo chương trình toán lớp 4 của Việt Nam.

            Chương trình toán lớp 4 ở Việt Nam bao gồm:
            - Phép tính với số tự nhiên: Cộng, trừ, nhân, chia với số lên đến hàng triệu (ví dụ: 2456 + 3789, 4860 ÷ 12).
            - Ước và bội: Tìm ước chung, bội chung, số nguyên tố, hợp số.
            - Phân số: So sánh, rút gọn, cộng, trừ phân số cùng mẫu (ví dụ: 3/5 + 1/5).
            - Hình học: Nhận biết hình (vuông, chữ nhật, tam giác); tính chu vi, diện tích hình vuông và chữ nhật (ví dụ: diện tích hình chữ nhật dài 8 cm, rộng 5 cm).
            - Đo lường: Đơn vị đo độ dài (mm, cm, m, km), thời gian (giờ, phút, giây), khối lượng (g, kg, tấn), tiền tệ; đổi đơn vị (ví dụ: 120 phút = 2 giờ).
            - Bài toán có lời văn: Bài toán về trung bình cộng, tỉ số, chuyển động (ví dụ: ô tô đi 120 km trong 2 giờ, tính vận tốc).
            - Dữ liệu: Đọc và phân tích biểu đồ cột đơn giản; thu thập và biểu diễn dữ liệu (ví dụ: bảng số liệu về số táo hái được trong 5 ngày).

            Cung cấp 5 gợi ý từng bước để giải bài toán, đảm bảo gợi ý phù hợp với trình độ lớp 4:
            - Bước 1 phải tập trung vào việc giải thích khái niệm hoặc công thức liên quan đến bài toán, dùng ví dụ gần gũi để bạn dễ hình dung (ví dụ: "Diện tích giống như số ô vuông nhỏ bên trong hình chữ nhật, bạn có biết không?").
            - Từ bước 2 trở đi, chia bài toán thành các bước nhỏ, dễ quản lý, mỗi bước xây dựng dựa trên bước trước.
            - Đặt câu hỏi gợi mở để khuyến khích bạn suy nghĩ (ví dụ: "Bạn thử cộng các số hàng chục trước xem được bao nhiêu?").
            - Sử dụng ngôn ngữ đơn giản, rõ ràng, tránh từ ngữ phức tạp hoặc ví dụ không liên quan (ví dụ: không dùng kẹo để giải thích vận tốc).
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải là một câu hoàn chỉnh, bằng tiếng Việt.

            Định dạng phản hồi là danh sách 5 gợi ý, mỗi gợi ý trên một dòng.
            """
        elif grade == "5":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 5 (10-11 tuổi) ở Việt Nam học toán bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải rõ ràng, khuyến khích, sử dụng ví dụ gần gũi, và phù hợp với độ tuổi. Mỗi gợi ý nên dẫn dắt bạn tiến gần hơn đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, thân thiện, phù hợp với học sinh lớp 5 ở Việt Nam.

            Chương trình toán lớp 5 ở Việt Nam bao gồm:
            - Số học: Phép tính với số thập phân, phân số, tỉ số phần trăm, diện tích, thể tích các hình cơ bản, bài toán chuyển động, bài toán có lời văn.
            - Hình học: Tính chu vi, diện tích hình vuông, hình chữ nhật, hình tam giác, hình tròn.
            - Đo lường: Đơn vị đo độ dài (mm, cm, m, km), thời gian (giờ, phút, giây), khối lượng (g, kg, tấn), tiền tệ; đổi đơn vị (ví dụ: 120 phút = 2 giờ).
            - Bài toán có lời văn: Bài toán về trung bình cộng, tỉ số, chuyển động (ví dụ: ô tô đi 120 km trong 2 giờ, tính vận tốc).
            - Dữ liệu: Đọc và phân tích biểu đồ cột đơn giản; thu thập và biểu diễn dữ liệu (ví dụ: bảng số liệu về số táo hái được trong 5 ngày).

            Cung cấp 5 gợi ý từng bước để giải bài toán, đảm bảo gợi ý phù hợp với trình độ lớp 5:
            - Bước 1: Giải thích yêu cầu của bài tập, khái niệm hoặc công thức liên quan.
            - Từ bước 2 trở đi: Chia thành các bước nhỏ, dễ làm, mỗi bước xây dựng dựa trên bước trước.
            - Đặt câu hỏi gợi mở để khuyến khích bạn suy nghĩ.
            - Sử dụng ngôn ngữ phù hợp với học sinh lớp 5, tránh từ ngữ chuyên ngành phức tạp.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải là một câu hoàn chỉnh, bằng tiếng Việt.

            Định dạng phản hồi là danh sách 5 gợi ý, mỗi gợi ý trên một dòng.
            """
        elif grade == "6":
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 6 (11-12 tuổi) ở Việt Nam học môn Ngữ Văn bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải rõ ràng, phù hợp với trình độ, và sử dụng ví dụ dễ hiểu. Mỗi gợi ý nên dẫn dắt bạn tiến gần hơn đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, thân thiện, phù hợp với học sinh lớp 6 ở Việt Nam.

            Chương trình Ngữ Văn lớp 6 ở Việt Nam bao gồm:
            - Văn học dân gian: Thần thoại, truyện cổ tích, ca dao, tục ngữ.
            - Văn học viết: Truyện ngắn, thơ, ký, văn miêu tả.
            - Lý luận văn học: Thể loại văn học, ngôn ngữ văn học, nhân vật, lời người kể chuyện.
            - Tiếng Việt: Từ vựng chuyên ngành, đồng nghĩa, trái nghĩa; các biện pháp tu từ (so sánh, nhân hóa).
            - Làm văn: Văn miêu tả, văn tự sự, văn biểu cảm; thuyết minh; viết đoạn, bài văn hoàn chỉnh.

            Cung cấp 5 gợi ý từng bước để giúp bạn, đảm bảo gợi ý phù hợp với trình độ lớp 6:
            - Bước 1: Giải thích yêu cầu của bài tập, các khái niệm cơ bản liên quan.
            - Từ bước 2 trở đi: Chia thành các bước nhỏ, dễ làm, mỗi bước xây dựng dựa trên bước trước.
            - Đặt câu hỏi gợi mở để khuyến khích bạn suy nghĩ.
            - Sử dụng ngôn ngữ phù hợp với học sinh lớp 6, đảm bảo chính xác về thuật ngữ văn học.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải là một câu hoàn chỉnh, bằng tiếng Việt.

            Định dạng phản hồi là danh sách 5 gợi ý, mỗi gợi ý trên một dòng.
            """
        else:  # Grade 7
            system_prompt = """
            Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 7 (12-13 tuổi) ở Việt Nam học môn Ngữ Văn bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải rõ ràng, chính xác và phù hợp với trình độ. Mỗi gợi ý nên dẫn dắt bạn tiến gần hơn đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, thân thiện, phù hợp với học sinh lớp 7 ở Việt Nam.

            Chương trình Ngữ Văn lớp 7 ở Việt Nam bao gồm:
            - Văn học dân gian: Truyện cổ tích, truyền thuyết, truyện cười, ca dao, tục ngữ, vè.
            - Văn học viết: Truyện ngắn, tiểu thuyết, kịch, thơ, ký.
            - Lý luận văn học: Thể loại văn học, đề tài, chủ đề, cốt truyện, không gian và thởi gian nghệ thuật.
            - Tiếng Việt: Từ ghép, từ láy; các biện pháp tu từ (ẩn dụ, hoán dụ, điệp từ); dấu câu.
            - Làm văn: Văn tự sự, văn miêu tả, văn biểu cảm, văn thuyết minh, văn nghị luận.

            Cung cấp 5 gợi ý từng bước để giúp bạn, đảm bảo gợi ý phù hợp với trình độ lớp 7:
            - Bước 1: Giải thích rõ ràng yêu cầu của bài tập, khái niệm cần nắm.
            - Từ bước 2 trở đi: Chia thành các bước nhỏ, dễ làm, mỗi bước xây dựng dựa trên bước trước.
            - Đặt câu hỏi gợi mở để khuyến khích bạn suy nghĩ.
            - Sử dụng ngôn ngữ phù hợp với học sinh lớp 7, đảm bảo chính xác về mặt học thuật.
            - Không đưa ra đáp án cuối cùng.
            - Mỗi gợi ý phải là một câu hoàn chỉnh, bằng tiếng Việt.

            Định dạng phản hồi là danh sách 5 gợi ý, mỗi gợi ý trên một dòng.
            """

    if file_path:
        logging.info(f"Processing file: {file_path}")
        # Kiểm tra file trước khi xử lý
        if not os.path.exists(file_path):
            logging.error(f"File not found: {file_path}")
            return ["File không tồn tại trên server. Bạn thử tải lại nhé!"] * (3 if grade == "2" else 5)

        file_type = "image/png" if file_path.lower().endswith(('.png', '.jpg', '.jpeg')) else "application/pdf"
        logging.info(f"File type detected: {file_type}")

        # Try to process with vision API first, if it fails, fall back to sending file directly to xAI
        vision_extraction_success = False
        try:
            # Trích xuất văn bản từ ảnh bằng Google Cloud Vision
            extracted_text = extract_text_from_image(file_path)
            if extracted_text:
                logging.info("Successfully extracted text with Vision API")
                
                # Tách bài toán cụ thể từ extracted_text
                specific_problem = extract_specific_problem(extracted_text, problem)
                if not specific_problem:
                    return ["Tớ không tìm thấy bài toán bạn yêu cầu. Bạn thử nhập lại nhé!"] * (3 if grade == "2" else 5)
                # Gửi bài toán cụ thể cho API
                user_prompt = f"""
                Bài toán: {specific_problem}
                Lớp: {grade}
                """
            else:
                logging.warning("Vision API returned no text")
        except Exception as e:
            logging.error(f"Error using Vision API: {str(e)}", exc_info=True)
            extracted_text = None
        
        # If Vision API failed or returned no text, try direct file upload to xAI
        if not vision_extraction_success:
            logging.warning("No text extracted from image. Falling back to API with file.")
            user_prompt = """
            Người dùng đã tải lên một hình ảnh hoặc file PDF chứa các bài toán. Nhiệm vụ của bạn là:
            1. Trích xuất toàn bộ nội dung từ hình ảnh hoặc file PDF. Nội dung thường bao gồm nhiều bài toán được đánh số thứ tự (ví dụ: "Câu 1", "Câu 2",...).
            2. Nếu trích xuất thành công, xác định danh sách các bài toán theo số thứ tự (ví dụ: "Câu 1", "Câu 2",...) từ nội dung đã trích xuất.
            3. Nếu người dùng chưa nhập yêu cầu cụ thể (problem rỗng hoặc không có), trả về danh sách các bài toán đã trích xuất và hỏi: "Tớ thấy các bài toán: [danh sách]. Bạn muốn hỏi về câu nào?"
            4. Nếu không trích xuất được nội dung từ file, trả về: "Tớ không đọc được nội dung file. Bạn thử nhập thủ công bài toán nhé!"
            Định dạng phản hồi:
            - Nếu là danh sách bài toán: trả về một dòng duy nhất với nội dung: "Tớ thấy các bài toán: [danh sách]. Bạn muốn hỏi về câu nào?"
            - Nếu là thông báo lỗi: một dòng duy nhất.
            """
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt,
                    "files": [
                        {
                            "file": base64.b64encode(open(file_path, "rb").read()).decode("utf-8"),
                            "type": file_type
                        }
                    ]
                }
            ],
            "model": "grok-3-latest",
            "stream": False,
            "temperature": 0.7,
            "max_tokens": 500
        }
    else:
        # Regular text query without file
        user_prompt = f"""
        Bài toán: {problem}
        Lớp: {grade}
        """
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            "model": "grok-3-latest",
            "stream": False,
            "temperature": 0.7,
            "max_tokens": 500
        }
    for attempt in range(retries):
        try:
            # Backoff delay tăng dần theo số lần thử 
            if attempt > 0:
                backoff_time = delay * (2 ** (attempt - 1))  # 2, 4, 8... giây
                logging.info(f"Retry {attempt}/{retries} - Waiting {backoff_time}s before retry...")
                sleep(backoff_time)

            logging.info(f"Calling xAI API (attempt {attempt + 1}/{retries})...")
            
            # Tăng timeout từ 20s lên 30s
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            logging.info(f"xAI API response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            
            # Lưu log chi tiết hơn về response 
            logging.info(f"API Response (Status {response.status_code})")
            if "choices" in data and len(data["choices"]) > 0:
                response_text = data["choices"][0]["message"]["content"].strip()
                lines = response_text.strip().split("\n")
                if len(lines) == 1:
                    if "Tớ thấy các bài toán" in lines[0]:
                        return lines
                    elif "Tớ không đọc được" in lines[0] or "Tớ gặp khó khăn" in lines[0] or "Tớ không nhận diện được" in lines[0]:
                        return lines + ["Bạn thử nhập lại hoặc chọn bài toán khác nhé!"] * (2 if grade == "2" else 4)
                while len(lines) < (3 if grade == "2" else 5):
                    lines.append("Bạn thử áp dụng gợi ý trước để giải bài toán nhé!")
                
                # Lưu cache kết quả khi thành công
                if problem and not file_path:
                    cache_key = f"{problem}_grade_{grade}_subject_{subject}"
                    HINT_CACHE[cache_key] = lines[:(3 if grade == "2" else 5)]
                    if len(HINT_CACHE) > 100:  # Tăng kích thước cache
                        oldest_key = next(iter(HINT_CACHE))
                        HINT_CACHE.pop(oldest_key)
                    logging.info(f"Cached result for problem: {problem}")
                
                usage = data.get("usage", {})
                total_tokens = usage.get("total_tokens", 0)
                if "token_usage" not in session:
                    session["token_usage"] = []
                session["token_usage"].append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "problem": f"Image analysis",
                    "total_tokens": total_tokens
                })
                session["token_usage"] = session["token_usage"][-50:]
                session.modified = True
                return lines[:(3 if grade == "2" else 5)]
            else:
                logging.warning(f"Unexpected API response format: {data}")
                if attempt == retries - 1:
                    logging_message = f"Failed after {retries} attempts with API. Returning default response."
                    logging.error(logging_message)
                    return ["Tớ gặp trục trặc khi lấy gợi ý. Bạn thử lại sau nhé!"] * (3 if grade == "2" else 5)
        except requests.exceptions.Timeout:
            logging.error(f"Attempt {attempt + 1}/{retries} - Timeout error calling xAI API")
            if attempt == retries - 1:
                return ["API bị timeout. Bạn thử lại sau nhé!"] * (3 if grade == "2" else 5)
        except requests.exceptions.RequestException as e:
            logging.error(f"Attempt {attempt + 1}/{retries} - Error calling xAI API: {str(e)}")
            if attempt == retries - 1:
                return ["Tớ gặp khó khăn khi kết nối với API. Bạn thử lại sau nhé!"] * (3 if grade == "2" else 5)

demo_hint = "Nhập bài toán hoặc tải ảnh để nhận gợi ý!"

@app.route("/", methods=["GET", "POST"])
def welcome():
    global demo_hint
    if request.method == "POST" and "demo_question" in request.form:
        question = request.form.get("demo_question", "").strip()
        grade = session.get("grade", "4")
        hints = call_xai_api(question, grade)
        demo_hint = hints[0]
        return render_template("welcome.html", demo_hint=demo_hint)
    return render_template("welcome.html", demo_hint=demo_hint)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        return redirect(url_for("role"))
    return render_template("login.html")

@app.route("/role", methods=["GET", "POST"])
def role():
    if request.method == "POST":
        role = request.form.get("role")
        grade = request.form.get("grade")
        subject = request.form.get("subject", "math")  # Mặc định là môn Toán
        if grade:
            session["grade"] = grade
        if subject:
            session["subject"] = subject
        if role == "kids":
            return redirect(url_for("kids"))
        elif role == "parent":
            return redirect(url_for("parent"))
    return render_template("role.html")

@app.route("/kids", methods=["GET", "POST"])
def kids():
    logging.info(f"Current session['grade']: {session.get('grade', '4')}")
    if "current_step" not in session:
        session["current_step"] = 0
    if "current_question" not in session:
        session["current_question"] = ""
    if "cache_key" not in session:
        session["cache_key"] = None
    if "recent_questions" not in session:
        session["recent_questions"] = []
    if "attached_file" not in session:
        session["attached_file"] = None
    if "extracted_problems" not in session:
        session["extracted_problems"] = None
    if "extraction_status" not in session:
        session["extraction_status"] = ""

    if request.method == "GET":
        session["current_question"] = ""
        session["current_step"] = 0
        session["cache_key"] = None
        session["image_path"] = None
        session["attached_file"] = None
        session["recent_questions"] = []
        session["extracted_problems"] = None
        session["extraction_status"] = ""
        session.modified = True

    # Đặt hint mặc định chung, thân thiện cho trẻ em và phù hợp cả Toán lẫn Tiếng Việt
    hint = "Nhập bài toán, bài tập Tiếng Việt hoặc tải ảnh đề bài để nhận gợi ý nhé! Đừng ngại hỏi bất cứ điều gì, tớ luôn sẵn sàng giúp bạn! 😊"
    tip = ""
    image_path = None
    loading = False
    loading_message = "Cho tớ suy nghĩ chút nhé!"

    if request.method == "POST":
        action = request.form.get("action")
        question = request.form.get("question", "").strip()
        file = request.files.get('file')
        clear_file = request.form.get("clear_file", "false").lower() == "true"

        if action == "attach_file" and file:
            session["current_question"] = ""
            session["current_step"] = 0
            session["cache_key"] = None
            session["image_path"] = None
            session["recent_questions"] = []
            session["extracted_problems"] = None
            
            # Remove old file if exists
            if session.get("attached_file"):
                try:
                    os.remove(session["attached_file"])
                    logging.info(f"Removed old attached file: {session['attached_file']}")
                except Exception as e:
                    logging.error(f"Error removing old attached file: {str(e)}")
            
            # Check if file is valid
            if file and file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf')):
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"upload_{timestamp}_{file.filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                try:
                    # Save file
                    file.save(file_path)
                    file_size = os.path.getsize(file_path)
                    logging.info(f"File saved: {file_path}, size: {file_size} bytes")
                    # Normalize path for consistent handling
                    session["attached_file"] = file_path.replace('\\', '/')
                    logging.info(f"File uploaded successfully: {session['attached_file']}")
                    
                    # Set status and UI
                    hint = "File đã được tải lên thành công. Đang tự động trích xuất nội dung..."
                    loading = True
                    loading_message = "Đang trích xuất nội dung file. Quá trình này có thể mất vài giây..."
                    session["extraction_status"] = "extracting"
                    
                    # Try immediate extraction
                    try:
                        extracted_text = extract_text_from_image(session['attached_file'])
                        if extracted_text:
                            logging.info("Successfully extracted text immediately")
                            
                            # Parse problems directly from the text
                            problems = []
                            patterns = [r'Bài\s+\d+', r'Câu\s+\d+', r'Bài\s+toán\s+\d+']
                            
                            for pattern in patterns:
                                matches = re.findall(pattern, extracted_text)
                                if matches:
                                    problems.extend(matches)
                                    break
                            
                            if problems:
                                # Create problem list text
                                problems_str = ", ".join(problems)
                                problem_list = f"Tớ thấy các bài toán: {problems_str}. Bạn muốn hỏi về bài nào?"
                                
                                logging.info(f"Immediately generated problem list: {problem_list}")
                                session["extracted_problems"] = problem_list
                                loading = False
                                hint = problem_list
                                session["extraction_status"] = "completed"
                    except Exception as e:
                        logging.error(f"Error extracting text immediately: {str(e)}")
                        # Continue with normal flow if immediate extraction fails
                
                except Exception as e:
                    logging.error(f"Error saving uploaded file: {str(e)}")
                    hint = "Có lỗi khi lưu file. Bạn thử tải lại nhé!"
                    session["attached_file"] = None
                    loading = False
            else:
                hint = "File không hợp lệ. Vui lòng tải lên file ảnh (PNG, JPG, JPEG) hoặc PDF."
                loading = False
                session["attached_file"] = None
            
            session.modified = True
            
            # Prepare response
            response = make_response(render_template("kids.html", hint=hint, tip=tip, loading=loading, 
                                               current_question=session["current_question"], 
                                               current_step=session["current_step"],
                                               recent_questions=session["recent_questions"], 
                                               image_path=session.get("image_path"),
                                               attached_file=session.get("attached_file"),
                                               extracted_problems=session.get("extracted_problems"),
                                               extraction_status=session.get("extraction_status", ""),
                                               loading_message=loading_message,
                                               timestamp=int(time())))
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

        elif action == "extract_content":
            logging.info("Starting content extraction...")
            if not session.get("attached_file"):
                logging.error("No attached_file found in session")
                hint = "Không tìm thấy file để trích xuất. Bạn thử tải lại nhé!"
                session["attached_file"] = None
                session["extraction_status"] = ""
                loading = False
                session.modified = True
                return render_template("kids.html", hint=hint, tip=tip, loading=loading, 
                                     current_question=session["current_question"], 
                                     current_step=session["current_step"],
                                     recent_questions=session["recent_questions"], 
                                     image_path=session.get("image_path"),
                                     attached_file=session.get("attached_file"),
                                     extracted_problems=session.get("extracted_problems"),
                                     extraction_status=session.get("extraction_status", ""),
                                     loading_message=loading_message,
                                     timestamp=int(time()))

            logging.info(f"Attached file path: {session['attached_file']}")
            if not os.path.exists(session['attached_file']):
                logging.error(f"File does not exist at path: {session['attached_file']}")
                hint = "File không tồn tại trên server. Bạn thử tải lại nhé!"
                session["attached_file"] = None
                session["extraction_status"] = ""
                loading = False
                session.modified = True
                return render_template("kids.html", hint=hint, tip=tip, loading=loading, 
                                     current_question=session["current_question"], 
                                     current_step=session["current_step"],
                                     recent_questions=session["recent_questions"], 
                                     image_path=session.get("image_path"),
                                     attached_file=session.get("attached_file"),
                                     extracted_problems=session.get("extracted_problems"),
                                     loading_message=loading_message,
                                     timestamp=int(time()))
            
            hint = "Đang trích xuất nội dung từ file..."
            loading = True
            loading_message = "Quá trình này có thể mất vài giây, vui lòng đợi..."
            session["extraction_status"] = "extracting"
            session.modified = True
            
            # First return response to update UI, then perform extraction
            response = make_response(render_template("kids.html", hint=hint, tip=tip, loading=loading, 
                                               current_question=session["current_question"], 
                                               current_step=session["current_step"],
                                               recent_questions=session["recent_questions"], 
                                               image_path=session.get("image_path"),
                                               attached_file=session.get("attached_file"),
                                               extracted_problems=session.get("extracted_problems"),
                                               extraction_status=session.get("extraction_status", ""),
                                               loading_message=loading_message,
                                               timestamp=int(time())))
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

        elif action == "check_extraction":
            logging.info("Checking extraction status...")
            
            # First check if we already have extracted problems
            if session.get("extracted_problems"):
                hint = session["extracted_problems"]
                logging.info(f"Already have extracted problems: {hint}")
                loading = False
                session["extraction_status"] = "completed"
                session.modified = True
                return jsonify({"status": "completed", "result": hint})
            
            # If no attached file, return error
            if not session.get("attached_file"):
                logging.info("No attached_file found in session")
                return jsonify({"status": "error", "message": "No extraction in progress"})
            
            try:
                logging.info(f"Checking Google credentials file exists: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")
                logging.info(f"Credential file exists: {os.path.exists(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])}")
                
                # Try to extract text directly
                extracted_text = extract_text_from_image(session['attached_file'])
                if extracted_text:
                    logging.info("Successfully extracted text with Vision API")
                    
                    # Parse problems directly from the text
                    problems = []
                    patterns = [r'Bài\s+\d+', r'Câu\s+\d+', r'Bài\s+toán\s+\d+']
                    
                    for pattern in patterns:
                        matches = re.findall(pattern, extracted_text)
                        if matches:
                            problems.extend(matches)
                            break
                    
                    if problems:
                        # Create problem list text
                        problems_str = ", ".join(problems)
                        problem_list = f"Tớ thấy các bài toán: {problems_str}. Bạn muốn hỏi về bài nào?"
                        
                        logging.info(f"Generated problem list: {problem_list}")
                        session["extracted_problems"] = problem_list
                        session["extraction_status"] = "completed"
                        session.modified = True
                        return jsonify({"status": "completed", "result": problem_list})
                    else:
                        logging.info("No problems found in extracted text")
                
                # Fall back to API if direct extraction didn't work
                grade = session.get("grade", "4")
                cache_key = f"extracted_{session['attached_file']}"
                if cache_key in EXTRACTED_CONTENT:
                    extracted_result = EXTRACTED_CONTENT[cache_key]
                    logging.info(f"Using cached extracted content: {extracted_result}")
                else:
                    logging.info("Calling call_xai_api function...")
                    extracted_result = call_xai_api("", grade, session["attached_file"])
                    logging.info(f"call_xai_api returned: {extracted_result}")
                    EXTRACTED_CONTENT[cache_key] = extracted_result
                    if len(EXTRACTED_CONTENT) > 50:
                        EXTRACTED_CONTENT.pop(next(iter(EXTRACTED_CONTENT)))
                
                # Process results
                result = ""
                if len(extracted_result) > 0 and "Tớ thấy các bài toán" in extracted_result[0]:
                    logging.info("Found problem list in response")
                    session["extracted_problems"] = extracted_result[0]
                    result = extracted_result[0]
                    session["extraction_status"] = "completed"
                    session.modified = True
                    return jsonify({"status": "completed", "result": result})
                elif len(extracted_result) > 0 and any(x in extracted_result[0] for x in ["Tớ không đọc được", "Tớ gặp khó khăn", "Tớ không nhận diện được"]):
                    logging.info(f"Error message detected in response: {extracted_result[0]}")
                    result = f"{extracted_result[0]} Bạn có thể nhập thủ công bài toán nhé!"
                    session["attached_file"] = None
                    session["extraction_status"] = "completed"
                    session.modified = True
                    return jsonify({"status": "completed", "result": result})
                else:
                    logging.warning(f"Unexpected response format: {extracted_result}")
                    result = "Tớ không trích xuất được nội dung rõ ràng. Bạn thử nhập thủ công bài toán nhé!"
                    session["attached_file"] = None
                    session["extraction_status"] = "completed"
                    session.modified = True
                    return jsonify({"status": "completed", "result": result})
                
            except Exception as e:
                logging.error(f"Error during extraction check: {str(e)}", exc_info=True)
                return jsonify({
                    "status": "error", 
                    "message": "Có lỗi xảy ra khi trích xuất nội dung. Bạn thử lại sau."
                })

        elif action == "attach_complete":
            logging.info("Starting attach_complete action (DEPRECATED)...")
            # This is the old implementation, keeping for backward compatibility
            # In new code, we'll use extraction_status and check_extraction instead

        elif action == "ask":
            logging.info(f"Starting ask action with question: {question}")
            if clear_file and session.get("attached_file"):
                try:
                    os.remove(session["attached_file"])
                    logging.info(f"Removed attached file due to clear_file: {session['attached_file']}")
                except Exception as e:
                    logging.error(f"Error removing attached file: {str(e)}")
                session["attached_file"] = None
            
            # Xử lý clear_extracted_problems
            clear_extracted_problems = request.form.get("clear_extracted_problems", "false").lower() == "true"
            if clear_extracted_problems:
                session["extracted_problems"] = None
                logging.info("Cleared extracted_problems due to clear_extracted_problems flag")

            # Nếu user chọn bài toán từ danh sách sau OCR
            direct_question = request.form.get("direct_question")
            if direct_question and session.get("attached_file") and session.get("extraction_status") == "completed":
                # Tách số hiệu problem ("Câu N" hoặc "Bài N") từ direct_question
                match = re.match(r"((Câu|Bài)\s*\d+)", direct_question)
                if match:
                    problem_id = match.group(1)
                else:
                    problem_id = direct_question.strip().split(" ")[0]  # fallback
                extracted_text = extract_text_from_image(session["attached_file"])
                specific_problem = extract_specific_problem(extracted_text, problem_id)
                if specific_problem:
                    session["current_question"] = specific_problem
                    session["current_step"] = 0
                    session["cache_key"] = None
                    loading = True
                    loading_message = "Cho tớ suy nghĩ chút nhé!"
                    session["image_path"] = None
                    session.modified = True
                    # Gọi API chỉ với nội dung bài toán đã chọn
                    grade = session.get("grade", "4")
                    hints = call_xai_api(specific_problem, grade)
                    hint = hints[0] if hints else "Tớ chưa nghĩ ra gợi ý. Bạn thử lại nhé!"
                    loading = False
                    session["extracted_problems"] = None
                    session["extraction_status"] = ""
                    response = make_response(render_template("kids.html", hint=hint, tip=tip, loading=loading, 
                                                           current_question=session["current_question"], 
                                                           current_step=session["current_step"],
                                                           recent_questions=session["recent_questions"], 
                                                           image_path=session.get("image_path"),
                                                           attached_file=session.get("attached_file"),
                                                           extracted_problems=session.get("extracted_problems"),
                                                           loading_message=loading_message,
                                                           timestamp=int(time())))
                    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                    response.headers["Pragma"] = "no-cache"
                    response.headers["Expires"] = "0"
                    return response
                else:
                    hint = "Tớ không tìm thấy nội dung bài toán bạn chọn. Bạn thử lại nhé!"
                    loading = False
                    session["current_question"] = ""
                    session["cache_key"] = None
                    session["image_path"] = None
                    response = make_response(render_template("kids.html", hint=hint, tip=tip, loading=loading, 
                                                           current_question=session["current_question"], 
                                                           current_step=session["current_step"],
                                                           recent_questions=session["recent_questions"], 
                                                           image_path=session.get("image_path"),
                                                           attached_file=session.get("attached_file"),
                                                           extracted_problems=session.get("extracted_problems"),
                                                           loading_message=loading_message,
                                                           timestamp=int(time())))
                    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                    response.headers["Pragma"] = "no-cache"
                    response.headers["Expires"] = "0"
                    return response
            # --- END PATCH: handle direct_question from OCR selection ---

            if question and not session.get("extracted_problems"):
                recent = session["recent_questions"]
                question = question[:100]
                if question not in recent:
                    recent.insert(0, question)
                    session["recent_questions"] = recent[:5]
                session["current_question"] = question
                session["current_step"] = 0
                session["cache_key"] = None
                loading = True
                loading_message = "Cho tớ suy nghĩ chút nhé!"
                if session.get("grade", "4") == "7" and is_geometry_problem(question):
                    image_path = get_geometry_image(question)
                    session["image_path"] = image_path
                else:
                    session["image_path"] = None
                session.modified = True
            elif session.get("extracted_problems") and question:
                session["current_question"] = question
                session["current_step"] = 0
                session["cache_key"] = None
                loading = True
                loading_message = "Cho tớ suy nghĩ chút nhé!"
                if session.get("grade", "4") == "7" and is_geometry_problem(question):
                    image_path = get_geometry_image(question)
                    session["image_path"] = image_path
                else:
                    session["image_path"] = None
                session.modified = True
            else:
                if session.get("extracted_problems"):
                    hint = session["extracted_problems"]
                else:
                    hint = "Bạn chưa nhập câu hỏi. Hãy nhập câu hỏi hoặc chọn một bài toán nhé!"
                session["current_question"] = ""
                session["cache_key"] = None
                session["image_path"] = None
                session.modified = True
            response = make_response(render_template("kids.html", hint=hint, tip=tip, loading=loading, 
                                                   current_question=session["current_question"], 
                                                   current_step=session["current_step"],
                                                   recent_questions=session["recent_questions"], 
                                                   image_path=session.get("image_path"),
                                                   attached_file=session.get("attached_file"),
                                                   extracted_problems=session.get("extracted_problems"),
                                                   loading_message=loading_message,
                                                   timestamp=int(time())))
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            return response

        elif action == "fetch_hints":
            logging.info(f"Fetching hints for question: {session.get('current_question', 'N/A')}")
            try:
                if not session.get("current_question"):
                    hint = "Bạn chưa chọn bài toán. Hãy chọn một câu hỏi nhé!"
                    if session.get("extracted_problems"):
                        hint = session["extracted_problems"]
                    loading = False
                    session.modified = True
                    return render_template("kids.html", hint=hint, tip=tip, loading=loading, 
                                         current_question=session["current_question"], 
                                         current_step=session["current_step"],
                                         recent_questions=session["recent_questions"], 
                                         image_path=session.get("image_path"),
                                         attached_file=session.get("attached_file"),
                                         extracted_problems=session.get("extracted_problems"),
                                         loading_message=loading_message,
                                         timestamp=int(time()))
                grade = session.get("grade", "4")
                sleep(2)
                cache_key = f"{session['current_question']}_grade_{grade}"
                if session.get("attached_file"):
                    cache_key += "_with_image"
                if cache_key in HINT_CACHE:
                    logging.info(f"Using cached hints for: {session['current_question']}")
                    hints = HINT_CACHE[cache_key]
                else:
                    standardized_question = standardize_math_input(session["current_question"])
                    hints = call_xai_api(standardized_question, grade, session.get("attached_file"))
                    HINT_CACHE[cache_key] = hints
                    if len(HINT_CACHE) > 50:
                        HINT_CACHE.pop(next(iter(HINT_CACHE)))
                session["cache_key"] = cache_key
                loading = False
                if len(hints) == 1 and "Tớ thấy các bài toán" in hints[0]:
                    hint = f"Tớ không tìm thấy {session['current_question']} trong danh sách. Bạn thử nhập lại hoặc chọn bài khác nhé!"
                    session["current_question"] = ""
                    session["extracted_problems"] = None
                else:
                    hint = hints[0] if hints else "Tớ không có gợi ý cho bài toán này. Bạn thử nhập lại hoặc chọn bài khác nhé!"
                    session["extracted_problems"] = None
                session.modified = True
                logging.info(f"Hints fetched successfully: {hints}")
            except Exception as e:
                logging.error(f"Error fetching hints: {str(e)}")
                loading = False
                if session.get("extracted_problems"):
                    hint = f"Có lỗi xảy ra khi lấy gợi ý cho bài toán này. Bạn thử chọn lại bài khác nhé!\n\n{session['extracted_problems']}"
                else:
                    hint = "Có lỗi xảy ra khi lấy gợi ý. Bạn thử lại sau nhé!"
                # KHÔNG xóa attached_file hay extracted_problems
                session.modified = True

        elif action == "explain_more":
            cache_key = session.get("cache_key")
            max_steps = 3 if session.get("grade", "4") == "2" else 5
            hints = HINT_CACHE.get(cache_key, ["Tớ không có gợi ý cho bài toán này."] * max_steps)
            if session["current_step"] < len(hints) - 1:
                session["current_step"] += 1
                hint = hints[session["current_step"]]
            else:
                hint = "Đó là gợi ý cuối cùng rồi! Bạn thử giải bài toán nhé."
            session.modified = True

        elif action == "got_it":
            hint = "Bạn giỏi lắm!"
            session["current_step"] = 0
            session["cache_key"] = None
            session["current_question"] = ""
            session["image_path"] = None
            # KHÔNG xóa attached_file hay extracted_problems
            session.modified = True

        elif action == "clear_history":
            session["recent_questions"] = []
            # KHÔNG xóa attached_file hay extracted_problems
            session.modified = True
            hint = "Lịch sử bài toán đã được xóa!"

    if session.get("cache_key"):
        max_steps = 3 if session.get("grade", "4") == "2" else 5
        hints = HINT_CACHE.get(session["cache_key"], ["Nhập bài toán hoặc tải ảnh để nhận gợi ý!"] * max_steps)
        hint = hints[session["current_step"]] if session["current_step"] < len(hints) else "Nhập bài toán hoặc tải ảnh để nhận gợi ý!"

    response = make_response(render_template("kids.html", hint=hint, tip=tip, loading=loading, 
                                           current_question=session["current_question"], 
                                           current_step=session["current_step"],
                                           recent_questions=session["recent_questions"], 
                                           image_path=session.get("image_path"),
                                           attached_file=session.get("attached_file"),
                                           extracted_problems=session.get("extracted_problems"),
                                           loading_message=loading_message,
                                           timestamp=int(time())))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response
    
@app.route("/get_parent_tip", methods=["GET"])
def get_parent_tip():
    if "current_question" in session and session["current_question"]:
        tip = get_parent_tip_from_api(session["current_question"])
        return jsonify({"tip": tip})
    else:
        return jsonify({"tip": "Hãy khuyến khích con nhập một bài toán để nhận mẹo cụ thể nhé!"})

@app.route("/parent", methods=["GET", "POST"])
def parent():
    if request.method == "POST":
        return redirect(url_for("role"))
    return render_template("parent.html")

@app.route("/api_usage", methods=["GET"])
def api_usage():
    if "token_usage" not in session:
        return "Chưa có dữ liệu token usage."
    
    today = date.today().strftime("%Y-%m-%d")
    total_tokens = 0
    usage_log = session["token_usage"]
    daily_usage = [entry for entry in usage_log if entry["timestamp"].startswith(today)]
    
    for entry in daily_usage:
        total_tokens += entry["total_tokens"]
    
    input_tokens = total_tokens * 0.7
    output_tokens = total_tokens * 0.3
    cost = (input_tokens / 1_000_000 * 5) + (output_tokens / 1_000_000 * 15)
    
    return f"Tổng token hôm nay ({today}): {total_tokens}<br>Chi phí ước tính: ${cost:.4f}"

@app.route('/tmp/<path:filename>')
def serve_tmp_file(filename):
    return send_from_directory('tmp', filename)

if __name__ == "__main__":
    app.run(debug=True)
