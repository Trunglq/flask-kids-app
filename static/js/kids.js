// Global state
let isProcessingRequest = false;
let pendingHintFetch = false;
let isExtractionMode = false;
let extractionErrorCount = 0;
let pollCount = 0;

// Wait for the document to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
    console.log("DOM fully loaded. Running fixed script.");
    
    // Force reset any stuck state
    resetProcessingState();
    
    // Add event listeners for buttons
    setupEventListeners();
    
    // Check for files
    const fileInput = document.getElementById('file-input');
    if (fileInput) {
        fileInput.addEventListener('change', function() {
            if (fileInput.files.length > 0) {
                console.log("File selected, submitting form...");
                resetProcessingState();
                submitFileForm();
            }
        });
    }
    
    // Scroll chat to bottom
    scrollChatToBottom();
});

// Reset all processing state flags
function resetProcessingState() {
    console.log("Resetting processing state");
    isProcessingRequest = false;
    isExtractionMode = false;
    pendingHintFetch = false;
    extractionErrorCount = 0;
    pollCount = 0;
}

// Submit form for file upload
function submitFileForm() {
    console.log("Submitting file form");
    const form = document.getElementById('main-form');
    if (!form) {
        console.error("Form not found");
        return;
    }
    
    // Create FormData and add action
    const formData = new FormData(form);
    formData.append('action', 'attach_file');
    
    // Show loading state
    showLoadingState("Đang tải file lên...");
    
    // Set processing flag
    isProcessingRequest = true;
    
    // Submit form via fetch
    fetch('/kids', {
        method: 'POST',
        body: formData,
        cache: 'no-store'
    })
    .then(response => response.text())
    .then(html => {
        console.log("File upload complete");
        
        // Update page content
        updatePageContent(html);
        
        // Start polling for extraction status immediately
        // since we're now automatically starting extraction
        isExtractionMode = true;
        setTimeout(pollExtractionStatus, 1000);
    })
    .catch(error => {
        console.error("Error uploading file:", error);
        showError("Lỗi khi tải file: " + error.message);
        isProcessingRequest = false;
    });
}

// Function to start extraction process
function startExtraction(updateUI = true) {
    console.log("Starting extraction process...");
    
    // Only reset state and update UI if explicitly requested
    if (updateUI) {
        resetProcessingState();
        showLoadingState("Đang trích xuất nội dung...");
    }
    
    isExtractionMode = true;
    isProcessingRequest = true;
    
    // Submit extraction request
    fetch('/kids', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: 'action=extract_content',
        cache: 'no-store'
    })
    .then(response => response.text())
    .then(html => {
        console.log("Extraction started");
        
        // Begin polling for status
        setTimeout(pollExtractionStatus, 1000);
    })
    .catch(error => {
        console.error("Error starting extraction:", error);
        showError("Lỗi khi bắt đầu trích xuất: " + error.message);
        resetProcessingState();
    });
}

// Poll for extraction status
function pollExtractionStatus() {
    console.log("Polling extraction status...");
    if (!isProcessingRequest || !isExtractionMode) {
        console.log("Extraction polling stopped");
        return;
    }
    
    // Show proper polling UI if not already shown
    const loadingText = document.querySelector('.loading-text');
    if (loadingText && !loadingText.textContent.includes('trích xuất')) {
        updateLoadingMessage("Đang trích xuất nội dung file...");
    }
    
    fetch('/kids', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: 'action=check_extraction',
        cache: 'no-store'
    })
    .then(response => response.json())
    .catch(error => {
        // If response isn't JSON, try to check if it's HTML with problem list
        console.log("Response not JSON, checking for HTML content");
        return { status: "check_html" };
    })
    .then(data => {
        console.log("Extraction status:", data);
        
        // If we need to check HTML (not JSON response)
        if (data.status === "check_html") {
            // Try to look for problem list in the page content
            const contentSection = document.querySelector('.content-section');
            const problemListContainer = document.querySelector('.problem-list-container');
            
            if (problemListContainer && problemListContainer.textContent.includes("Tớ thấy các bài toán")) {
                console.log("Found problem list in HTML content!");
                // Make problem numbers clickable
                makeProblemsClickable(problemListContainer.textContent);
                resetProcessingState();
                return;
            }
            
            // If no problem list found but we're no longer loading, reset state
            const appConfig = document.getElementById('app-config');
            if (appConfig && appConfig.getAttribute('data-loading') !== 'true') {
                console.log("No longer in loading state, resetting");
                resetProcessingState();
                return;
            }
            
            // Keep polling
            pollCount = (pollCount || 0) + 1;
            setTimeout(pollExtractionStatus, 1000);
            return;
        }
        
        if (data.status === 'completed') {
            // Update UI with result
            const contentSection = document.querySelector('.content-section');
            if (contentSection) {
                if (data.result.includes("Tớ thấy các bài toán")) {
                    // Make problem numbers clickable
                    makeProblemsClickable(data.result);
                } else {
                    contentSection.innerHTML = `
                        <p class="hint-text">${data.result}</p>
                    `;
                }
            }
            
            // Reset state
            resetProcessingState();
        } else if (data.status === 'error') {
            showError(data.message || "Lỗi khi trích xuất nội dung");
            resetProcessingState();
        } else {
            // Still processing - update the message to show progress
            pollCount = (pollCount || 0) + 1;
            
            // Vary the message based on how long it's taking
            let progressMessage;
            if (pollCount < 3) {
                progressMessage = "Đang trích xuất nội dung file...";
            } else if (pollCount < 6) {
                progressMessage = "Đang phân tích văn bản từ file...";
            } else if (pollCount < 10) {
                progressMessage = "Quá trình này có thể mất thêm vài giây...";
            } else {
                progressMessage = "Đang hoàn tất việc trích xuất...";
            }
            
            updateLoadingMessage(progressMessage);
            
            // If we've been polling for too long, check page content directly
            if (pollCount > 20) {
                const contentSection = document.querySelector('.content-section');
                if (contentSection && contentSection.textContent.includes("Tớ thấy các bài toán")) {
                    console.log("Found problem list after many attempts!");
                    // Make problem numbers clickable
                    makeProblemsClickable(contentSection.textContent);
                    resetProcessingState();
                    return;
                }
            }
            
            // Poll again more frequently for better responsiveness
            setTimeout(pollExtractionStatus, 1000);
        }
    })
    .catch(error => {
        console.error("Error checking extraction status:", error);
        extractionErrorCount++;
        
        if (extractionErrorCount < 3) {
            setTimeout(pollExtractionStatus, 2000);
        } else {
            showError("Không thể kết nối với server. Hãy tải lại trang và thử lại.");
            resetProcessingState();
        }
    });
}

// Helper functions
function showLoadingState(message) {
    const contentSection = document.querySelector('.content-section');
    if (contentSection) {
        contentSection.innerHTML = `
            <div class="loading-container">
                <div class="loading-bar"></div>
                <p class="loading-text">${message}</p>
            </div>
        `;
    }
}

function updateLoadingMessage(message) {
    const loadingText = document.querySelector('.loading-text');
    if (loadingText) {
        loadingText.textContent = message;
    }
}

function showError(message) {
    console.error("Error:", message);
    const contentSection = document.querySelector('.content-section');
    if (contentSection) {
        contentSection.innerHTML = `
            <p class="hint-text" style="color: #e53935;">${message}</p>
            <p>Bạn có thể:</p>
            <ul>
                <li>Thử tải lại trang</li>
                <li>Thử tải lên file khác</li>
                <li>Nhập câu hỏi trực tiếp vào ô nhập</li>
            </ul>
        `;
    }
    resetProcessingState();
}

function updatePageContent(html) {
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = html;
    
    // Find content section
    const newContentSection = tempDiv.querySelector('.content-section');
    const contentSection = document.querySelector('.content-section');
    if (newContentSection && contentSection) {
        contentSection.innerHTML = newContentSection.innerHTML;
    }
    
    // Find chat column
    const newChatColumn = tempDiv.querySelector('.chat-column');
    const chatColumn = document.querySelector('.chat-column');
    if (newChatColumn && chatColumn) {
        chatColumn.innerHTML = newChatColumn.innerHTML;
        scrollChatToBottom();
    }
}

function scrollChatToBottom() {
    const chatColumn = document.querySelector('.chat-column');
    if (chatColumn) {
        chatColumn.scrollTop = chatColumn.scrollHeight;
    }
}

function setupEventListeners() {
    // This will be called after DOM is loaded to set up any event listeners
    // that might be needed for buttons or other elements
    console.log("Setting up event listeners");
}

// --- Gợi ý từng bước bằng AJAX ---
let currentStep = 1;
let allHints = [];

function getNextHint() {
    const questionInput = document.querySelector('textarea[name="question"]');
    const question = questionInput ? questionInput.value.trim() : '';
    if (!question) return;

    const btn = document.getElementById('next-hint-btn');
    if (btn) btn.disabled = true;

    fetch('/get_hint_step', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: `question=${encodeURIComponent(question)}&step=${currentStep}`
    })
    .then(res => res.json())
    .then(data => {
        if (data.hint) {
            allHints.push(data.hint);
            renderHints();
            currentStep += 1;
        }
        if (btn) btn.disabled = false;
    })
    .catch(() => { if (btn) btn.disabled = false; });
}

function renderHints() {
    const hintBox = document.getElementById('step-hints-box');
    if (hintBox) {
        hintBox.innerHTML = allHints.map((h, i) => `<div class='hint-step'>Bước ${i+1}: ${h}</div>`).join('');
    }
}

window.getNextHint = getNextHint;

// Add a debug button to force reset state
function addResetButton() {
    const contentSection = document.querySelector('.content-section');
    if (contentSection) {
        const resetButton = document.createElement('button');
        resetButton.innerText = "Reset Processing State";
        resetButton.style.backgroundColor = "#f44336";
        resetButton.style.color = "white";
        resetButton.style.padding = "10px";
        resetButton.style.marginTop = "10px";
        resetButton.style.border = "none";
        resetButton.style.borderRadius = "5px";
        resetButton.style.cursor = "pointer";
        
        resetButton.onclick = function() {
            resetProcessingState();
            alert("Processing state has been reset!");
        };
        
        contentSection.appendChild(resetButton);
    }
}

// Expose functions to global scope
window.startExtraction = startExtraction;
window.resetProcessingState = resetProcessingState;
window.addResetButton = addResetButton;

// Add emergency reset method activated by pressing Ctrl+Shift+R
document.addEventListener('keydown', function(event) {
    if (event.ctrlKey && event.shiftKey && event.key === 'R') {
        console.log("Emergency reset triggered by keyboard shortcut");
        resetProcessingState();
        addResetButton();
        alert("Emergency reset performed!");
        event.preventDefault();
    }
});

// Helper functions
function showTwoStepMessage(firstMessage, secondMessage) {
    const contentSection = document.querySelector('.content-section');
    if (contentSection) {
        contentSection.innerHTML = `
            <p class="hint-text">${firstMessage}</p>
            <div class="loading-container">
                <div class="loading-bar"></div>
                <p class="loading-text">${secondMessage}</p>
            </div>
        `;
    }
}

// Function to make problem numbers clickable
function makeProblemsClickable(problemText) {
    console.log("Making problems clickable:", problemText);
    
    const contentSection = document.querySelector('.content-section');
    if (!contentSection) return;
    
    // Extract the text portion about problems
    const problemPortion = problemText.includes("Tớ thấy các bài toán") 
        ? problemText 
        : "Tớ thấy các bài toán: " + problemText;
    
    // Use regex to identify the problem numbers (Bài X or Câu X)
    const problemMatches = [...problemPortion.matchAll(/(\bBài\s+\d+\b|\bCâu\s+\d+\b)/g)];
    
    if (problemMatches.length > 0) {
        // Create intro text
        let htmlContent = `<p class="hint-text">Tớ thấy các bài toán: `;
        
        // Create clickable links for each problem
        problemMatches.forEach((match, index) => {
            const problemNumber = match[0];
            htmlContent += `<a href="javascript:void(0)" onclick="selectProblem('${problemNumber}')" class="problem-link">${problemNumber}</a>`;
            
            // Add comma or ending text
            if (index < problemMatches.length - 1) {
                htmlContent += ", ";
            } else {
                htmlContent += ". Bạn muốn hỏi về bài nào?</p>";
            }
        });
        
        // Add styling for problem links
        const styleElement = document.createElement('style');
        styleElement.textContent = `
            .problem-link {
                color: #1E88E5;
                text-decoration: none;
                font-weight: bold;
                background-color: #e3f2fd;
                padding: 2px 6px;
                border-radius: 4px;
                margin: 0 2px;
            }
            .problem-link:hover {
                background-color: #1E88E5;
                color: white;
                text-decoration: none;
            }
        `;
        document.head.appendChild(styleElement);
        
        // Update content section
        contentSection.innerHTML = htmlContent;
    } else {
        // Fallback if no matches found
        contentSection.innerHTML = `<p class="hint-text">${problemPortion}</p>`;
    }
}

function handleExtractedProblems(html) {
    console.log("Checking for extracted problems in response");
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = html;
    
    // First, check if there's any hint containing "Tớ thấy các bài toán"
    const hints = tempDiv.querySelectorAll('.hint-text');
    if (hints.length > 0) {
        console.log("Found hints:", hints.length);
        for (const hint of hints) {
            console.log("Hint content:", hint.textContent);
            if (hint.textContent.includes("Tớ thấy các bài toán") || 
                hint.textContent.includes("Bài 1") || 
                hint.textContent.includes("Câu 1")) {
                console.log("Found extracted problems in hint!");
                
                // Make the problems clickable
                makeProblemsClickable(hint.textContent);
                
                // Clear loading state
                isProcessingRequest = false;
                return true;
            }
        }
    }
    
    // Then check for problem list container
    const problemListContainer = tempDiv.querySelector('.problem-list-container');
    if (problemListContainer) {
        console.log("Found problem list container:", problemListContainer.textContent);
        // Extract the list of problems
        const problemText = problemListContainer.textContent;
        if (problemText.includes("Tớ thấy các bài toán") || 
            problemText.includes("Bài 1") || 
            problemText.includes("Câu 1")) {
            console.log("Found problem list text");
            
            // Make the problems clickable
            makeProblemsClickable(problemText);
            
            // Clear loading state
            isProcessingRequest = false;
            return true;
        }
    }
    
    // As a final fallback, check for any text that might contain the problems list
    const fullText = tempDiv.textContent;
    if (fullText.includes("Tớ thấy các bài toán") || 
        (fullText.includes("Bài 1") && fullText.includes("Bài 2")) || 
        (fullText.includes("Câu 1") && fullText.includes("Câu 2"))) {
        console.log("Found problems in full text");
        
        // Extract the relevant portion with regex
        const regex = /(Tớ thấy các bài toán[^\.]+)/;
        const match = regex.exec(fullText);
        if (match) {
            const problemsText = match[1];
            console.log("Extracted problems text:", problemsText);
            
            // Make the problems clickable
            makeProblemsClickable(problemsText);
            
            // Clear loading state
            isProcessingRequest = false;
            return true;
        }
    }
    
    return false;
} 