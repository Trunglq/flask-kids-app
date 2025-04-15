# Task List for AI for Kids Project

## Project Overview
- Current Status: Prototype running locally, supports Math for grades 1-7, file/image uploads, 5-step prompts via xAI API, and parent tips.
- Short-term Goals: Deploy on Vercel, test with 5-10 users, prepare for fundraising ($75,000).

## Tasks

### 1. Deploy Prototype on Vercel
- [ ] Install Vercel CLI
  - Command: `npm i -g vercel`
- [ ] Create `vercel.json` configuration file
  - Content:
    ```json
    {
        "version": 2,
        "builds": [
            {
                "src": "app.py",
                "use": "@vercel/python"
            }
        ],
        "routes": [
            {
                "src": "/(.*)",
                "dest": "app.py"
            }
        ]
    }
 Deploy to Vercel
Navigate to project directory: cd ai-for-kids
Run: vercel deploy
 Test deployed app
Use 20-30 sample questions (Math grades 4-7).
Ensure 5-step prompts and parent tips work correctly.
2. Test with 5-10 Users
 Prepare a list of 5-10 friends/parents to test the app
Create a simple Google Form for feedback (e.g., "Did the prompts help your child?", "Was the parent tip useful?").
 Share Vercel link with testers
Send via email/WhatsApp with instructions: "Ask a Math question (grades 4-7), upload an image if needed, and provide feedback."
 Collect feedback
Compile responses from Google Form or direct messages.
Look for common issues (e.g., prompts not clear, UI confusing).
3. Prepare for Fundraising
 Create a pitch deck (10-15 slides)
Slide 1: Title (AI for Kids)
Slide 2: Problem (Kids lack critical thinking, parents lack pedagogical skills)
Slide 3: Solution (5-step guided prompts + parent tips)
Slide 4: Market (EdTech K-12, $190B by 2025)
Slide 5: Product (Prototype demo, Vercel link)
Slide 6: Traction (Feedback from 5-10 users)
Slide 7: Team (You: UI/UX, past experience with Kidy.vn)
Slide 8: Competition (Khan Academy, BYJU’s, but we focus on guided thinking)
Slide 9: Business Model (Future: Freemium, subscription for premium features)
Slide 10: Ask ($75,000 for MVP, testing, team)
 Record a demo video
1-2 minutes, screen recording of the app on Vercel (show asking a Math question, 5 prompts, parent tip).
 Submit application to investors
Target: Emerge Education, 500 Startups Vietnam.
Include pitch deck, demo video, and Vercel link.
4. Future Tasks (After Feedback)
 Build backend for user management
Features: Sign-up/login, track user questions, manage roles (kid/parent).
 Add more subjects (Grade 2 Math, Literature)
Prepare 10-15 sample questions for each subject.
Adjust xAI prompt if needed for Literature.
Notes
Replace "your_xai_api_key_here" in app.py with your actual xAI API key.
UI optimization is deferred until after fundraising.
Focus on traction (user feedback) to strengthen fundraising pitch.