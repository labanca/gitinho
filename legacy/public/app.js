document.addEventListener('DOMContentLoaded', () => {
    const chatMessages = document.getElementById('chat-messages');
    const repoForm = document.getElementById('repo-form');

    function addMessage(content, isUser = false) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${isUser ? 'user' : ''}`;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';
        contentDiv.innerHTML = isUser ? content : marked.parse(content);
        
        messageDiv.appendChild(contentDiv);
        chatMessages.appendChild(messageDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    repoForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        const owner = document.getElementById('owner').value.trim();
        const repo = document.getElementById('repo').value.trim();
        
        if (!owner || !repo) return;

        // Add user message
        addMessage(`Analyzing repository: ${owner}/${repo}`, true);

        try {
            const response = await fetch('/analyze', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ owner, repo })
            });

            if (!response.ok) {
                throw new Error('Failed to analyze repository');
            }

            const data = await response.json();
            addMessage(data.analysis);
        } catch (error) {
            addMessage('Sorry, there was an error analyzing the repository. Please try again.');
            console.error('Error:', error);
        }

        // Clear inputs
        document.getElementById('owner').value = '';
        document.getElementById('repo').value = '';
    });

    // Add welcome message
    addMessage('Welcome to Gitinho! Enter a GitHub repository owner and name to get an AI-powered analysis.');
});