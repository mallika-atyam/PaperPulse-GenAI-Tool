# PaperPulse Execution Guide (Step-by-Step)

This guide provides complete, step-by-step instructions for running **PaperPulse** in both **Automated Quick Run** mode and through the interactive **Swagger UI** browser interface.

---

## 🛠️ Step 0: Prerequisites & Environment Setup

Before running either mode, ensure your virtual environment is activated and your API keys are configured.

### 1. Activate the Virtual Environment
Open your terminal (PowerShell or Command Prompt on Windows) in the project root:
```powershell
# In PowerShell:
.venv\Scripts\activate

# (You will see (.venv) at the beginning of your terminal prompt)
```

### 2. Verify Your `.env` File
Open [.env](file:///d:/Own%20Projects/PaperPulse/.env) and ensure your keys are configured:
```env
# JWT Secret
SECRET_KEY=paperpulse-dev-secret-key-3849182390123
JWT_SECRET_KEY=paperpulse-dev-secret-key-3849182390123

# LLM Providers (PaperPulse automatically falls back between providers if one is unavailable or out of quota)
GROQ_API_KEY=gsk_your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b

OPENAI_API_KEY=sk-proj-your_openai_api_key
OPENAI_MODEL=gpt-4o-mini
```

---

## ⚡ Mode 1: Automated Quick Run (Demo Script)

If you want to test the entire pipeline programmatically in under 15 seconds without opening a browser:

```powershell
python colab_demo.py
```

### What This Does Automatically:
1. **Registers** a temporary student user (`POST /users`).
2. **Authenticates** and obtains a signed JWT Bearer token (`POST /auth/login`).
3. **Builds an academic PDF in-memory** about Transformers & Attention Mechanisms.
4. **Uploads the PDF** with PyMuPDF text extraction (`POST /materials/upload`).
5. **Generates an AI Summary** using your configured LLM (`POST /materials/{id}/summary`).
6. **Creates a Pydantic-validated MCQ Quiz** and prints the questions, options, correct answers, and explanations to your terminal (`POST /materials/{id}/quiz`).

---

## 🌐 Mode 2: Interactive Swagger UI (Step-by-Step Tutorial)

This mode allows you to visually test the application in your web browser like a client application (e.g. Postman or a frontend).

### 1. Start the FastAPI Development Server
In your terminal, run:
```powershell
uvicorn app.main:app --reload
```

You should see output similar to:
```text
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Application startup complete.
```

### 2. Open Swagger Documentation
Open your web browser and navigate to:
👉 **[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)**

---

### Step-by-Step Walkthrough in Swagger UI

#### 🟢 Step 1: Register a New User (`POST /users`)
1. In Swagger UI, scroll to the **Users** section.
2. Click on the row **`POST /users`** to expand it.
3. Click the **Try it out** button on the right.
4. In the **Request body** text area, replace the template with your desired user credentials:
   ```json
   {
     "email": "student@paperpulse.ai",
     "password": "MySecretPassword123!"
   }
   ```
5. Click the large blue **Execute** button.
6. **Expected Result**:
   - **Response code**: `201 Created`
   - **Response body**:
     ```json
     {
       "email": "student@paperpulse.ai",
       "id": 1
     }
     ```
   *(Note: The hashed password is never returned in responses).*

---

#### 🔐 Step 2: Authorize in Swagger UI (Log In)
FastAPI's Swagger UI has a built-in OAuth2 authentication dialog that stores your token for all subsequent requests:

1. Look at the top right of the Swagger page and click the green **Authorize** button (with the open padlock 🔓 icon).
2. A modal window titled **Available authorizations** will pop up:
   - **Username**: Enter the email you registered (`student@paperpulse.ai`).
   - **Password**: Enter the password you used (`MySecretPassword123!`).
   - *(Leave Client ID and Client Secret blank).*
3. Click **Authorize**.
4. You will see a green checkmark or confirmation. Click **Close**.
5. The padlock icon at the top right will now show as **Locked** (🔒). All your subsequent requests will automatically include the `Bearer <token>` authorization header!

---

#### 📄 Step 3: Upload a PDF Material (`POST /materials/upload`)
1. Scroll down to the **Materials** section.
2. Click on **`POST /materials/upload`** to expand it.
3. Click **Try it out**.
4. Under the **file** parameter, click **Choose File** (or **Browse**) and select any PDF document from your computer.
5. Click **Execute**.
6. **Expected Result**:
   - **Response code**: `201 Created`
   - **Response body**:
     ```json
     {
       "id": 1,
       "filename": "your_document.pdf",
       "status": "uploaded",
       "extracted_text_preview": "Abstract: ... [preview of the text extracted via PyMuPDF]"
     }
     ```
7. ⚠️ **Take note of the `id` number** returned (e.g. `1`). You will use this ID for the next steps!

---

#### 🧠 Step 4: Generate the AI Summary (`POST /materials/{id}/summary`)
1. Click on **`POST /materials/{id}/summary`** to expand it.
2. Click **Try it out**.
3. In the **id** field, enter your material ID (e.g. `1`).
4. Click **Execute**.
5. The LLM will analyze the extracted text and generate a structured summary.
6. **Expected Result**:
   - **Response code**: `200 OK`
   - **Response body**:
     ```json
     {
       "material_id": 1,
       "summary": "### Summary for your_document.pdf\n\n**Key Highlights:**\n- Core concepts...\n- Major takeaways...",
       "status": "completed"
     }
     ```

---

#### 📝 Step 5: Generate the Structured Quiz (`POST /materials/{id}/quiz`)
1. Click on **`POST /materials/{id}/quiz`** to expand it.
2. Click **Try it out**.
3. In the **id** field, enter your material ID (e.g. `1`).
4. In the **Request body**, you can optionally adjust the number of questions:
   ```json
   {
     "num_questions": 4
   }
   ```
5. Click **Execute**.
6. The LLM will generate multiple-choice questions conforming strictly to the `QuizSchema`.
7. **Expected Result**:
   - **Response code**: `200 OK`
   - **Response body**:
     ```json
     {
       "material_id": 1,
       "status": "completed",
       "quiz": {
         "title": "Quiz for your_document.pdf",
         "questions": [
           {
             "question": "What is the primary topic discussed in the text?",
             "options": [
               "Option A",
               "Option B",
               "Option C",
               "Option D"
             ],
             "correct_answer": "Option A",
             "explanation": "Explanation for why Option A is correct based on the text."
           }
         ]
       }
     }
     ```

---

#### 🔍 Step 6: Verify User Materials (`GET /materials` & `GET /materials/{id}`)
- Execute **`GET /materials`** to see a list of all materials associated with your account.
- Execute **`GET /materials/{id}`** with your material `id` to view the full document record, including the raw `extracted_text`, `summary`, and the stored `quiz_json` string.

---

## 💡 Troubleshooting & Tips

- **OpenAI 429 Insufficient Quota**: If your OpenAI key has an exhausted credit balance, PaperPulse will automatically fall back to Groq (if configured) or intelligent local synthesis without crashing.
- **Tesseract OCR on Scanned Files**: If you upload an image-based scanned PDF, PaperPulse will attempt OCR. For Windows users who need local OCR on scanned documents, ensure Tesseract is installed and path is set in `.env` (`TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`). Digital PDFs (text selectable) work instantly via PyMuPDF without requiring Tesseract.
