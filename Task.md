# Task List for Flask Kids App Development

## Upcoming Tasks

1. **Add API Prompt for Grades 1, 3, 5 and 6 in `app.py`**
   - Implement specific prompts for calling the API tailored to the curriculum and understanding level of Grade 1 (6-7 years old), Grade 3 (8-9 years old), Grade 5 (10-11 years old), and Grade 6 (11-12 years old) students in Vietnam.
   - Ensure the prompts are age-appropriate, using simple language and relatable examples for younger students, and slightly more complex concepts for older ones.
   - **Status**: Not done

2. **Add Grade 6 to Secondary School Level in `role.html`**
   - Update the role selection dropdown or interface in `role.html` to include Grade 6 under the Secondary School category (Cấp 2).
   - Ensure the selection reflects the Vietnamese education system structure.
   - **Status**: Not done

3. **Add Typical Math Problems for Grades 1, 3, 5 and 6 in `app.py` and `kids.html`**
   - In `app.py`, define typical math problems for each new grade level (1, 3, 5, and 6) that reflect common curriculum topics such as basic arithmetic for Grade 1, multiplication/division for Grade 3, and introductory algebra or geometry for Grade 6.
   - Update the 'Popular Problems' section in `kids.html` to dynamically display these typical problems based on the selected grade.
   - **Status**: Not done

4. **Add Vietnamese Language (Văn/Tiếng Việt) Subject for All Grades**
   - Extend the application to support Vietnamese language learning by adding a subject selection option in the role or main interface.
   - Develop prompts and typical questions for Vietnamese language topics appropriate to each grade level, covering areas like reading comprehension, grammar, and writing skills.
   - Update `app.py` to handle API calls for language-related queries and `kids.html` to display relevant content or problems for this subject.
   - **Status**: Not done

5. **Chọn ví dụ cho môn Tiếng Việt/Văn**
   - Đối với mỗi lớp cấp 1 (lớp 1, 2, 3, 4, 5), chọn ra 5 ví dụ bài tập hoặc câu hỏi điển hình về môn Tiếng Việt (như luyện đọc, chính tả, đặt câu, tìm từ, điền từ, v.v.).
   - Đối với mỗi lớp cấp 2 (lớp 6, 7), chọn ra 5 ví dụ bài tập hoặc câu hỏi điển hình về môn Văn (như đọc hiểu, phân tích đoạn thơ/văn, tìm biện pháp tu từ, viết đoạn văn, cảm nhận về nhân vật, v.v.).
   - **Status**: Not done

6. **Thêm tính năng "Gợi ý kiến thức liên quan"**
   - Tính năng này sẽ đưa ra các Định nghĩa/Khái niệm liên quan đến bài Toán/Văn mà user đang hỏi, được AI gợi ý.
   - Cập nhật giao diện và logic trong `app.py` và các tệp HTML liên quan để hiển thị các gợi ý kiến thức.
   - **Status**: Not done

7. **Tối ưu UI/UX cho responsive**
   - Cân nhắc sử dụng thư viện mở về UI để làm cho giao diện trông chuyên nghiệp hơn.
   - Đảm bảo ứng dụng hoạt động tốt trên các thiết bị khác nhau (desktop, tablet, mobile).
   - **Status**: Partially done (Responsive design has been implemented with mobile-first principles, but further enhancements or UI library integration are pending)

8. **Thêm tính năng "Góp ý về sản phẩm"**
   - Thêm một form hoặc nút để người dùng có thể gửi phản hồi hoặc góp ý về ứng dụng.
   - Cập nhật giao diện và xử lý backend để thu thập và lưu trữ các góp ý này.
   - **Status**: Not done

9. **Thêm phần "Kiến thức liên quan" gợi ý bởi AI bằng cách trích xuất tự động từ kiến thức trong bài mà user hỏi**
   - Implement a feature to automatically extract and display related knowledge or concepts from the user's query using AI suggestions.
   - Update the UI and backend logic to present this information alongside hints or answers.
   - **Status**: Not done

## Notes
- Ensure all updates align with the Vietnamese national curriculum for both Math and Vietnamese language subjects.
- Maintain the user-friendly and engaging interface for kids, using visuals and language that resonate with each age group.
- **Overall Progress Review**:
  - **Completed**: Basic app functionality, hint system for math problems (with some issues in hint repetition), responsive design groundwork.
  - **Partially Done**: UI/UX responsiveness (needs further optimization or library integration).
  - **Not Done**: Grade-specific prompts, additional grade levels, Vietnamese language subject support, typical problem sets, related knowledge features, feedback mechanism, and full UI/UX optimization.