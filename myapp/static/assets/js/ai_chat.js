document.addEventListener("DOMContentLoaded", function () {

    const chatbox = document.getElementById("ai-chatbox");
    const openBtn = document.getElementById("chatbox-open-btn");
    const closeBtn = document.getElementById("chatbox-toggle");

    const messagesBox = document.getElementById("ai-chat-messages");
    const input = document.getElementById("ai-chat-input-text");
    const sendBtn = document.getElementById("ai-chat-send-btn");

    if (!chatbox || !openBtn || !closeBtn || !messagesBox) {
        console.warn("Chatbox elements missing!");
        return;
    }

    // Open / Close
    openBtn.onclick = () => {
        chatbox.style.display = "flex";
        openBtn.style.display = "none";
    };

    closeBtn.onclick = () => {
        chatbox.style.display = "none";
        openBtn.style.display = "block";
    };

    // Bubble text
    function appendMessage(text, sender) {
        const div = document.createElement("div");
        div.className = "ai-msg " + sender;

        const span = document.createElement("span");
        span.textContent = text;

        div.appendChild(span);
        messagesBox.appendChild(div);
        messagesBox.scrollTop = messagesBox.scrollHeight;
    }

    // Format tiền VND
    function formatCurrencyVND(value) {
        try {
            return new Intl.NumberFormat("vi-VN", {
                style: "currency",
                currency: "VND",
            }).format(value);
        } catch {
            return value + " đ";
        }
    }

    // Hiển thị card sản phẩm (max 3)
    function renderProductSuggestions(products) {
        if (!products || !products.length) return;

        const wrapper = document.createElement("div");
        wrapper.classList.add("chat-product-suggestions");
        // 🔥 bắt buộc: đẩy xuống dưới bubble (vì bubble đang dùng float)
        wrapper.style.clear = "both";

        products.forEach(p => {
            const card = document.createElement("a");
            card.classList.add("chat-product-card");
            card.href = p.url;
            card.target = "_blank";

            const img = document.createElement("img");
            img.classList.add("chat-product-image");
            img.src = p.image || "";
            img.alt = p.name;

            const nameEl = document.createElement("div");
            nameEl.classList.add("chat-product-name");
            nameEl.textContent = p.name;

            const priceEl = document.createElement("div");
            priceEl.classList.add("chat-product-price");
            priceEl.textContent = formatCurrencyVND(p.price);

            card.appendChild(img);
            card.appendChild(nameEl);
            card.appendChild(priceEl);
            wrapper.appendChild(card);
        });

        messagesBox.appendChild(wrapper);
        messagesBox.scrollTop = messagesBox.scrollHeight;
    }

    // Gửi message
    async function sendMessage() {
        const text = input.value.trim();
        if (!text) return;

        appendMessage(text, "user");
        input.value = "";

        // Bubble "đang trả lời..."
        const loadingDiv = document.createElement("div");
        loadingDiv.className = "ai-msg bot";
        loadingDiv.innerHTML = "<span>Đang trả lời...</span>";
        messagesBox.appendChild(loadingDiv);
        messagesBox.scrollTop = messagesBox.scrollHeight;

        try {
            const res = await fetch("/api/ai-chat/", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text })
            });

            const data = await res.json();
            loadingDiv.remove();

            if (!res.ok) {
                appendMessage("Lỗi server: " + (data.error || res.status), "bot");
                return;
            }

            // Text trả lời
            appendMessage(data.reply || "Không nhận được phản hồi từ AI.", "bot");

            // Sản phẩm gợi ý
            if (data.products) {
                renderProductSuggestions(data.products);
            }

        } catch (err) {
            loadingDiv.remove();
            appendMessage("Không kết nối được tới server.", "bot");
        }
    }

    sendBtn.onclick = sendMessage;
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") sendMessage();
    });

});
