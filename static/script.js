document.addEventListener('DOMContentLoaded', () => {
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const chatHistory = document.getElementById('chat-history');

    function appendMessage(text, sender) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${sender}`;
        
        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        // Basic markdown/line break handling
        bubble.innerHTML = text.replace(/\n/g, '<br>');
        
        msgDiv.appendChild(bubble);
        chatHistory.appendChild(msgDiv);
        
        // Scroll to bottom
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    async function sendMessage() {
        const text = chatInput.value.trim();
        if (!text) return;

        // User message
        appendMessage(text, 'user');
        chatInput.value = '';

        // AI Typing indicator (simulated)
        const typingDiv = document.createElement('div');
        typingDiv.className = 'message ai typing';
        typingDiv.innerHTML = '<div class="bubble">...</div>';
        chatHistory.appendChild(typingDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight;

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ message: text })
            });

            const data = await response.json();
            
            // Remove typing indicator
            chatHistory.removeChild(typingDiv);
            
            // AI Response
            appendMessage(data.reply, 'ai');

        } catch (error) {
            chatHistory.removeChild(typingDiv);
            appendMessage("Connection error. VELA brain offline.", 'ai');
        }
    }

    sendBtn.addEventListener('click', sendMessage);
    
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendMessage();
        }
    });

    // Plaid Integration
    const linkButton = document.getElementById('link-button');
    if (linkButton) {
        linkButton.addEventListener('click', async () => {
            linkButton.disabled = true;
            linkButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Connecting...';
            try {
                const response = await fetch('/api/create_link_token', { method: 'POST' });
                const data = await response.json();
                
                if (data.link_token) {
                    const handler = Plaid.create({
                        token: data.link_token,
                        onSuccess: async (public_token, metadata) => {
                            await fetch('/api/set_access_token', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ public_token: public_token })
                            });
                            linkButton.innerHTML = '<i class="fas fa-check"></i> Bank Linked';
                            linkButton.style.background = 'rgba(16, 185, 129, 0.3)';
                            loadBalances();
                        },
                        onLoad: () => {
                            handler.open();
                        },
                        onExit: (err, metadata) => {
                            linkButton.disabled = false;
                            linkButton.innerHTML = '<i class="fas fa-plus"></i> Connect Bank';
                        }
                    });
                } else {
                    linkButton.disabled = false;
                    linkButton.innerHTML = 'Error initializing';
                }
            } catch (err) {
                console.error(err);
                linkButton.disabled = false;
                linkButton.innerHTML = 'Error';
            }
        });
    }

    async function loadBalances() {
        const balancesList = document.getElementById('balances-list');
        const balanceInsight = document.getElementById('balance-insight');
        if (!balancesList) return;

        try {
            const response = await fetch('/api/balances');
            const data = await response.json();
            
            if (data.status === 'success') {
                balancesList.innerHTML = data.data.replace(/\n/g, '<br>');
                balancesList.style.color = '#e2e8f0';
                if(balanceInsight) {
                    balanceInsight.innerHTML = '<em>VELA now has real-time access to your finances. Text her on WhatsApp to ask about your budget.</em>';
                }
                
                if (linkButton) {
                    linkButton.innerHTML = '<i class="fas fa-check"></i> Bank Linked';
                    linkButton.style.background = 'rgba(16, 185, 129, 0.3)';
                    linkButton.disabled = true;
                }
            }
        } catch (error) {
            console.error("Error fetching balances:", error);
        }
    }

    // Load balances on page load
    loadBalances();
});
