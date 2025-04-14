# Đặt backend Agg trước khi import pyplot
import matplotlib
matplotlib.use('Agg')  # Sử dụng backend không tương tác

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, make_response
from uuid import uuid4
import requests
from time import sleep, time
from datetime import datetime, date
import matplotlib.pyplot as plt
import os
import numpy as np
import re
import base64
import logging
import pytesseract
from PIL import Image

# Cấu hình logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
app.secret_key = "your_secret_key"
app.config['UPLOAD_FOLDER'] = 'static/images'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Giới hạn file upload 16MB

# Tạo thư mục static/images nếu chưa có
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

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
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img, lang='vie')
        logging.info(f"Text extracted from image: {text}")
        return text.strip()
    except Exception as e:
        logging.error(f"Error extracting text from image: {str(e)}")
        return None

def extract_specific_problem(extracted_text, problem):
    """
    Tách bài toán cụ thể từ extracted_text dựa trên problem (ví dụ: "Câu 5").
    Trả về bài toán đầy đủ (ví dụ: "Câu 5. Số thực là đơn thức có bậc ...").
    """
    try:
        # Chuẩn hóa problem
        problem = problem.strip()
        if problem.lower().startswith("câu"):
            problem = "Câu" + problem[3:]

        # Chia extracted_text thành các dòng
        lines = extracted_text.split('\n')
        problem_text = ""
        found = False

        # Tìm bài toán bắt đầu bằng problem
        for i, line in enumerate(lines):
            if line.strip().startswith(problem):
                found = True
                problem_text = line.strip()
                # Thêm các dòng tiếp theo cho đến khi gặp bài toán tiếp theo (bắt đầu bằng "Câu")
                for j in range(i + 1, len(lines)):
                    next_line = lines[j].strip()
                    if next_line.startswith("Câu"):
                        break
                    if next_line:
                        problem_text += "\n" + next_line
                break

        if found:
            logging.info(f"Extracted specific problem: {problem_text}")
            return problem_text
        else:
            logging.warning(f"Could not find problem: {problem}")
            return None
    except Exception as e:
        logging.error(f"Error extracting specific problem: {str(e)}")
        return None

def get_parent_tip_from_api(question, retries=1, delay=2):
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
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()
            logging.info(f"API Response for tip (Status {response.status_code}): {data}")
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
                return "Hãy khuyến khích con chia bài toán thành các bước nhỏ và hỏi: 'Con nghĩ bước đầu tiên mình cần làm gì?'"
        except requests.exceptions.RequestException as e:
            logging.error(f"Attempt {attempt + 1}/{retries} - Error calling xAI API for tip: {str(e)}")
            if attempt < retries - 1:
                logging.info(f"Retrying in {delay} seconds...")
                sleep(delay)
            else:
                return "Hãy khuyến khích con chia bài toán thành các bước nhỏ và hỏi: 'Con nghĩ bước đầu tiên mình cần làm gì?'"

def draw_triangle():
    try:
        logging.info("Drawing triangle...")
        fig, ax = plt.subplots()
        triangle = np.array([[0, 0], [3, 0], [1.5, 2.6], [0, 0]])
        ax.plot(triangle[:, 0], triangle[:, 1], 'b-')
        ax.text(0, 0, 'A', fontsize=12, ha='right')
        ax.text(3, 0, 'B', fontsize=12, ha='left')
        ax.text(1.5, 2.6, 'C', fontsize=12, ha='center', va='bottom')
        ax.set_xlim(-1, 4)
        ax.set_ylim(-1, 3)
        ax.set_aspect('equal')
        ax.axis('off')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = f"static/images/triangle_{timestamp}.png"
        plt.savefig(image_path, bbox_inches='tight')
        plt.close(fig)
        logging.info(f"Triangle saved at: {image_path}")
        return image_path
    except Exception as e:
        logging.error(f"Error drawing triangle: {str(e)}")
        return None

def draw_prism():
    try:
        logging.info("Drawing prism...")
        fig, ax = plt.subplots()
        base_bottom = np.array([[0, 0], [3, 0], [1.5, 1.5], [0, 0]])
        base_top = base_bottom + np.array([0, 3])
        ax.plot(base_bottom[:, 0], base_bottom[:, 1], 'b-')
        ax.plot(base_top[:, 0], base_top[:, 1], 'b-')
        for i in range(3):
            ax.plot([base_bottom[i, 0], base_top[i, 0]], [base_bottom[i, 1], base_top[i, 1]], 'b-')
        ax.text(0, 0, 'A', fontsize=12, ha='right')
        ax.text(3, 0, 'B', fontsize=12, ha='left')
        ax.text(1.5, 1.5, 'C', fontsize=12, ha='center', va='bottom')
        ax.text(0, 3, "A'", fontsize=12, ha='right')
        ax.text(3, 3, "B'", fontsize=12, ha='left')
        ax.text(1.5, 4.5, "C'", fontsize=12, ha='center', va='bottom')
        ax.set_xlim(-1, 4)
        ax.set_ylim(-1, 5)
        ax.set_aspect('equal')
        ax.axis('off')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = f"static/images/prism_{timestamp}.png"
        plt.savefig(image_path, bbox_inches='tight')
        plt.close(fig)
        logging.info(f"Prism saved at: {image_path}")
        return image_path
    except Exception as e:
        logging.error(f"Error drawing prism: {str(e)}")
        return None

def is_geometry_problem(question):
    geometry_keywords = ["tam giác", "hình lăng trụ", "đường thẳng", "góc", "hình hộp", "hình lập phương", "hình vuông", "hình chữ nhật"]
    return any(keyword in question.lower() for keyword in geometry_keywords)

def get_geometry_image(question):
    question_lower = question.lower()
    if "tam giác" in question_lower:
        return draw_triangle()
    elif "hình lăng trụ" in question_lower:
        return draw_prism()
    return None

def standardize_math_input(question):
    question = question.replace("goc A", "\\angle A").replace("goc B", "\\angle B").replace("goc C", "\\angle C")
    question = question.replace(" do", "^{\\circ}").replace("tam giac", "tam giác")
    question = re.sub(r'(\w+)\^2', r'\1^2', question)
    return question

def call_xai_api(problem=None, grade=None, file_path=None, retries=1, delay=2):
    check_rate_limit()
    
    url = "https://api.x.ai/v1/chat/completions"
    headers = {
        "Authorization": "Bearer xai-DCwUdnvyPe1EofmGW29GbglqUn2WU0WyiaWtmiaA2STEZoswhMwZrgtvhZoSbXzvdL3nnZ9iMyKIYXad",
        "Content-Type": "application/json"
    }
    
    if grade == "2":
        system_prompt = """
        Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 2 (7-8 tuổi) ở Việt Nam học toán bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải cực kỳ đơn giản, vui vẻ, và sử dụng ví dụ siêu gần gũi (như đếm kẹo, xếp đồ chơi, nhảy bước) để bạn dễ hiểu. Mỗi gợi ý dẫn bạn tiến gần đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, ngắn gọn, phù hợp với trẻ lớp 2 ở Việt Nam, và tuân theo chương trình toán lớp 2 của Việt Nam.

        Chương trình toán lớp 2 ở Việt Nam bao gồm:
        - Số học: Đếm, đọc, viết số đến 1000; cộng, trừ số trong phạm vi 1000 (ví dụ: 45 + 27, 83 - 19); nhân, chia số nhỏ (bảng cửu chương 2, 3, 4, 5).
        - Đo lường: Đo độ dài (cm, m), khối lượng (kg), thời gian (giờ, phút); xem đồng hồ (giờ đúng, giờ rưỡi).
        - Hình học: Nhận biết hình vuông, hình chữ nhật, hình tam giác, hình tròn.
        - Bài toán có lời văn: Bài toán đơn giản về cộng, trừ, nhân, chia (ví dụ: "Lan có 5 quả táo, mẹ cho thêm 3 quả, hỏi Lan có bao nhiêu quả?").

        Cung cấp 3 gợi ý từng bước để giải bài toán, đảm bảo gợi ý phù hợp với trình độ lớp 2:
        - Bước 1: Giải thích ý nghĩa bài toán hoặc phép tính bằng ví dụ gần gũi (ví dụ: "Cộng giống như gom kẹo lại với nhau, bạn thấy thế nào?").
        - Bước 2 và 3: Chia bài toán thành bước nhỏ, dễ làm, dùng câu hỏi vui để bạn suy nghĩ (ví dụ: "Nếu có 3 quả táo, thêm 2 quả nữa, bạn đếm được bao nhiêu ngón tay?").
        - Không dùng từ ngữ phức tạp, chỉ dùng từ trẻ lớp 2 hiểu (tránh "phương trình", "tính chất").
        - Không đưa ra đáp án cuối cùng.
        - Mỗi gợi ý là một câu hoàn chỉnh, bằng tiếng Việt, ngắn và vui.

        Định dạng phản hồi là danh sách 3 gợi ý, mỗi gợi ý trên một dòng.
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
    else:  # Grade 7
        system_prompt = """
        Bạn là một AI được thiết kế để làm bạn đồng hành, giúp học sinh lớp 7 (11-12 tuổi) ở Việt Nam học toán bằng cách cung cấp các gợi ý từng bước theo phương pháp giàn giáo (scaffolding). Tớ xưng là "tớ", gọi bạn học sinh là "bạn" để thân thiện như một người bạn cùng tuổi. Các gợi ý phải rõ ràng, chi tiết, và sử dụng ví dụ thực tế phù hợp (như tính tiền tiết kiệm, đo đạc thực tế) để bạn dễ liên tưởng. Mỗi gợi ý nên dẫn dắt bạn tiến gần hơn đến đáp án mà không đưa ra đáp án cuối cùng. Sử dụng ngôn ngữ tự nhiên, thân thiện, phù hợp với trẻ lớp 7 ở Việt Nam, và tuân theo chương trình toán lớp 7 của Việt Nam.

        Chương trình toán lớp 7 ở Việt Nam bao gồm:
        - Đại số:
          + Số hữu tỉ, số thực: Các phép tính với số hữu tỉ, số vô tỉ, căn bậc hai, giá trị tuyệt đối, làm tròn số, tỉ lệ thức, đại lượng tỉ lệ thuận/nghịch (ví dụ: Tính \( \frac{3}{4} + \frac{5}{6} \), tìm \( x \) trong \( \frac{2}{3} = \frac{x}{9} \)).
          + Hàm số và đồ thị: Khái niệm hàm số, đồ thị hàm số \( y = ax \) (a ≠ 0).
          + Thống kê: Thu thập dữ liệu, bảng tần số, tần suất, mốt, số trung bình cộng.
          + Biểu thức đại số: Đơn thức, đa thức, cộng trừ đa thức, nghiệm của đa thức một biến (ví dụ: Rút gọn \( (2x^2 - 3x + 5) + (x^2 + 4x - 1) \)).
        - Hình học:
          + Góc và đường thẳng song song: Góc ở vị trí đặc biệt, tia phân giác, hai đường thẳng song song, tiên đề Euclid (ví dụ: Tính góc so le trong).
          + Tam giác: Tổng các góc, các trường hợp bằng nhau (cạnh-cạnh-cạnh, cạnh-góc-cạnh, góc-cạnh-góc), tam giác cân, tam giác đều, đường trung trực.
          + Quan hệ trong tam giác: Quan hệ giữa góc và cạnh, bất đẳng thức tam giác, tính chất đường trung tuyến, phân giác, trung trực (ví dụ: Chứng minh tam giác bằng nhau).
          + Hình khối: Hình hộp chữ nhật, lăng trụ đứng, tính diện tích xung quanh, thể tích (ví dụ: Tính thể tích lăng trụ đứng tam giác).

        Cung cấp 5 gợi ý từng bước để giải bài toán, đảm bảo gợi ý phù hợp với trình độ lớp 7:
        - Bước 1 phải tập trung vào việc giải thích khái niệm, công thức, hoặc định lý liên quan đến bài toán, trích dẫn định nghĩa nếu cần (ví dụ: "Định lý: Tổng ba góc trong một tam giác bằng 180°. Bạn có biết không?").
        - Từ bước 2 trở đi, chia bài toán thành các bước nhỏ, dễ quản lý, mỗi bước xây dựng dựa trên bước trước.
        - Đặt câu hỏi gợi mở để khuyến khích bạn suy nghĩ (ví dụ: "Bạn thử thay số vào công thức xem được bao nhiêu?").
        - Sử dụng ngôn ngữ rõ ràng, tránh từ ngữ phức tạp, và mô tả hình vẽ bằng chữ nếu cần (ví dụ: "Tam giác ABC có AB = 5 cm, AC = 6 cm, góc A = 40°.").
        - Không đưa ra đáp án cuối cùng.
        - Mỗi gợi ý phải là một câu hoàn chỉnh, bằng tiếng Việt.

        Định dạng phản hồi là danh sách 5 gợi ý, mỗi gợi ý trên một dòng.
        """

    if file_path:
        # Kiểm tra file trước khi xử lý
        if not os.path.exists(file_path):
            logging.error(f"File not found: {file_path}")
            return ["File không tồn tại trên server. Bạn thử tải lại nhé!"] * (3 if grade == "2" else 5)

        file_type = "image/png" if file_path.lower().endswith(('.png', '.jpg', '.jpeg')) else "application/pdf"
        logging.info(f"File type detected: {file_type}")

        # Trích xuất văn bản từ ảnh bằng Tesseract
        extracted_text = extract_text_from_image(file_path)
        if not extracted_text:
            logging.warning("No text extracted from image. Falling back to API with file.")
            user_prompt = """
            Người dùng đã tải lên một hình ảnh hoặc file PDF chứa các bài toán. Nhiệm vụ của bạn là:
            1. Trích xuất toàn bộ nội dung từ hình ảnh hoặc file PDF. Nội dung thường bao gồm nhiều bài toán được đánh số thứ tự (ví dụ: "Câu 1", "Câu 2",...).
            2. Nếu trích xuất thành công, xác định danh sách các bài toán theo số thứ tự (ví dụ: "Câu 1", "Câu 2",...).
            3. Nếu người dùng chưa nhập yêu cầu cụ thể (problem rỗng hoặc không có), trả về danh sách các bài toán đã trích xuất và hỏi: "Tớ thấy các bài toán: [danh sách]. Bạn muốn hỏi về câu nào?"
            4. Nếu không trích xuất được nội dung từ file, trả về: "Tớ không đọc được nội dung file. Bạn thử nhập thủ công bài toán nhé!"
            Định dạng phản hồi:
            - Nếu là danh sách bài toán: trả về một dòng duy nhất với nội dung: "Tớ thấy các bài toán: [danh sách]. Bạn muốn hỏi về câu nào?"
            - Nếu là thông báo lỗi: một dòng duy nhất.
            """
            try:
                with open(file_path, "rb") as f:
                    file_base64 = base64.b64encode(f.read()).decode("utf-8")
                logging.info(f"File encoded to base64 successfully: {file_path}")
            except Exception as e:
                logging.error(f"Error encoding file to base64: {str(e)}")
                return ["Có lỗi khi đọc file. Bạn thử tải lại nhé!"] * (3 if grade == "2" else 5)

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
                                "file": file_base64,
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
            # Nếu Tesseract trích xuất được văn bản
            if problem:
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
                # Nếu không có problem, yêu cầu API trả về danh sách bài toán
                user_prompt = f"""
                Dưới đây là nội dung trích xuất từ file ảnh:\n{extracted_text}\n
                Nhiệm vụ của bạn là:
                1. Xác định danh sách các bài toán theo số thứ tự (ví dụ: "Câu 1", "Câu 2",...) từ nội dung đã trích xuất.
                2. Trả về danh sách các bài toán đã trích xuất và hỏi: "Tớ thấy các bài toán: [danh sách]. Bạn muốn hỏi về câu nào?"
                3. Nếu không xác định được bài toán nào từ nội dung, trả về: "Tớ không nhận diện được bài toán nào từ nội dung. Bạn thử nhập thủ công nhé!"
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
                logging.info(f"Calling xAI API (attempt {attempt + 1}/{retries})...")
                response = requests.post(url, headers=headers, json=payload, timeout=15)
                response.raise_for_status()
                data = response.json()
                logging.info(f"API Response (Status {response.status_code}): {data}")
                if "choices" in data and len(data["choices"]) > 0:
                    response_text = data["choices"][0]["message"]["content"]
                    lines = response_text.strip().split("\n")
                    if len(lines) == 1:
                        if "Tớ thấy các bài toán" in lines[0]:
                            return lines
                        elif "Tớ không tìm thấy" in lines[0] or "Tớ không đọc được" in lines[0] or "Tớ không nhận diện được" in lines[0]:
                            return lines + ["Bạn thử nhập lại hoặc chọn bài toán khác nhé!"] * (2 if grade == "2" else 4)
                    while len(lines) < (3 if grade == "2" else 5):
                        lines.append("Bạn thử áp dụng gợi ý trước để giải bài toán nhé!")
                    usage = data.get("usage", {})
                    total_tokens = usage.get("total_tokens", 0)
                    if "token_usage" not in session:
                        session["token_usage"] = []
                    session["token_usage"].append({
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "problem": problem if problem else "Image analysis",
                        "total_tokens": total_tokens
                    })
                    session["token_usage"] = session["token_usage"][-50:]
                    session.modified = True
                    return lines[:(3 if grade == "2" else 5)]
                else:
                    logging.warning(f"Unexpected API response format: {data}")
                    return ["Tớ gặp trục trặc khi lấy gợi ý. Bạn thử lại sau nhé!"] * (3 if grade == "2" else 5)
            except requests.exceptions.RequestException as e:
                logging.error(f"Attempt {attempt + 1}/{retries} - Error calling xAI API: {str(e)}")
                if attempt < retries - 1:
                    logging.info(f"Retrying in {delay} seconds...")
                    sleep(delay)
                else:
                    return ["Tớ gặp khó khăn khi kết nối với API. Bạn thử lại sau nhé!"] * (3 if grade == "2" else 5)
    else:
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
                logging.info(f"Calling xAI API (attempt {attempt + 1}/{retries})...")
                response = requests.post(url, headers=headers, json=payload, timeout=15)
                response.raise_for_status()
                data = response.json()
                logging.info(f"API Response (Status {response.status_code}): {data}")
                if "choices" in data and len(data["choices"]) > 0:
                    response_text = data["choices"][0]["message"]["content"]
                    lines = response_text.strip().split("\n")
                    while len(lines) < (3 if grade == "2" else 5):
                        lines.append("Bạn thử áp dụng gợi ý trước để giải bài toán nhé!")
                    usage = data.get("usage", {})
                    total_tokens = usage.get("total_tokens", 0)
                    if "token_usage" not in session:
                        session["token_usage"] = []
                    session["token_usage"].append({
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "problem": problem if problem else "Image analysis",
                        "total_tokens": total_tokens
                    })
                    session["token_usage"] = session["token_usage"][-50:]
                    session.modified = True
                    return lines[:(3 if grade == "2" else 5)]
                else:
                    logging.warning(f"Unexpected API response format: {data}")
                    return ["Tớ gặp trục trặc khi lấy gợi ý. Bạn thử lại sau nhé!"] * (3 if grade == "2" else 5)
            except requests.exceptions.RequestException as e:
                logging.error(f"Attempt {attempt + 1}/{retries} - Error calling xAI API: {str(e)}")
                if attempt < retries - 1:
                    logging.info(f"Retrying in {delay} seconds...")
                    sleep(delay)
                else:
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
        if grade:
            session["grade"] = grade
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

    if request.method == "GET":
        session["current_question"] = ""
        session["current_step"] = 0
        session["cache_key"] = None
        session["image_path"] = None
        session["attached_file"] = None
        session["recent_questions"] = []
        session["extracted_problems"] = None
        session.modified = True

    hint = "Nhập bài toán hoặc tải ảnh để nhận gợi ý!"
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
            if session.get("attached_file"):
                try:
                    os.remove(session["attached_file"])
                    logging.info(f"Removed old attached file: {session['attached_file']}")
                except Exception as e:
                    logging.error(f"Error removing old attached file: {str(e)}")
            if file and file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.pdf')):
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"upload_{timestamp}_{file.filename}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                try:
                    file.save(file_path)
                    file_size = os.path.getsize(file_path)
                    logging.info(f"File saved: {file_path}, size: {file_size} bytes")
                    session["attached_file"] = file_path
                    logging.info(f"File uploaded successfully: {file_path}")
                except Exception as e:
                    logging.error(f"Error saving uploaded file: {str(e)}")
                    hint = "Có lỗi khi lưu file. Bạn thử tải lại nhé!"
                    session["attached_file"] = None
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
                hint = "Ảnh đã được tải lên. Đang trích xuất nội dung..."
                loading = True
                loading_message = "Đang tải và trích xuất nội dung file..."
            else:
                hint = "File không hợp lệ. Vui lòng tải lên file ảnh (PNG, JPG, JPEG) hoặc PDF."
                loading = False
                session["attached_file"] = None
            session.modified = True

        elif action == "attach_complete":
            logging.info("Starting attach_complete action...")
            try:
                if not session.get("attached_file"):
                    hint = "Không tìm thấy file để trích xuất. Bạn thử tải lại nhé!"
                    session["attached_file"] = None
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
                cache_key = f"extracted_{session['attached_file']}"
                if cache_key in EXTRACTED_CONTENT:
                    extracted_result = EXTRACTED_CONTENT[cache_key]
                    logging.info("Using cached extracted content.")
                else:
                    extracted_result = call_xai_api("", grade, session["attached_file"])
                    EXTRACTED_CONTENT[cache_key] = extracted_result
                    if len(EXTRACTED_CONTENT) > 50:
                        EXTRACTED_CONTENT.pop(next(iter(EXTRACTED_CONTENT)))
                    logging.info(f"Extracted content: {extracted_result}")
                if "Tớ thấy các bài toán" in extracted_result[0]:
                    session["extracted_problems"] = extracted_result[0]
                    hint = extracted_result[0]
                elif "Tớ không đọc được" in extracted_result[0] or "Tớ gặp khó khăn" in extracted_result[0]:
                    hint = f"{extracted_result[0]} Bạn có thể nhập thủ công bài toán nhé!"
                    session["attached_file"] = None
                else:
                    hint = "Tớ không trích xuất được nội dung. Bạn thử nhập thủ công nhé!"
                    session["attached_file"] = None
                loading = False
            except Exception as e:
                logging.error(f"Error during attach_complete: {str(e)}")
                hint = "Có lỗi xảy ra khi trích xuất nội dung. Bạn thử tải lại hoặc nhập thủ công nhé!"
                session["attached_file"] = None
                loading = False
            session.modified = True

        elif action == "ask":
            logging.info(f"Starting ask action with question: {question}")
            if clear_file and session.get("attached_file"):
                try:
                    os.remove(session["attached_file"])
                    logging.info(f"Removed attached file due to clear_file: {session['attached_file']}")
                except Exception as e:
                    logging.error(f"Error removing attached file: {str(e)}")
                session["attached_file"] = None
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
                hint = "Có lỗi xảy ra khi lấy gợi ý. Bạn thử lại sau nhé!"
                session["attached_file"] = None
                session["extracted_problems"] = None
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
            session["extracted_problems"] = None
            if session.get("attached_file"):
                try:
                    os.remove(session["attached_file"])
                    logging.info(f"Removed attached file: {session['attached_file']}")
                except Exception as e:
                    logging.error(f"Error removing attached file: {str(e)}")
            session["attached_file"] = None
            session["recent_questions"] = []
            session.modified = True

        elif action == "clear_history":
            session["recent_questions"] = []
            session["attached_file"] = None
            session["extracted_problems"] = None
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

if __name__ == "__main__":
    app.run(debug=False)