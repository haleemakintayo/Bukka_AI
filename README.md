# 🥘 Bukka AI (Powered by Llama 4 Maverick)

![Status](https://img.shields.io/badge/Status-Live_Beta-success?style=for-the-badge)
![Model](https://img.shields.io/badge/Model-Llama_4_Maverick_17B-blueviolet?style=for-the-badge)
![Platform](https://img.shields.io/badge/Platform-Telegram_Bot-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)

> **"The Agentic Sales Manager for African MSMEs."**

**Bukka AI** is a next-gen Agentic CRM built for Nigerian food vendors. It replaces chaotic manual replies with an intelligent, bilingual AI agent ("Auntie Chioma") that lives on **Telegram**.

Powered by the bleeding-edge **Meta Llama 4 Maverick (17B MoE)**, it offers the reasoning of a giant model with the speed required for real-time commerce.

---

## 🚀 Why Llama 4 Maverick?
We chose `meta-llama/llama-4-maverick-17b-128e-instruct` for three critical reasons:

1. **Mixture-of-Experts (MoE) Speed:** With 128 experts but only ~17B active parameters, it runs fast enough for instant Telegram replies while retaining 400B-level reasoning to understand deep **Nigerian Pidgin**.
2. **Agentic Reliability:** "Maverick" is optimized for tool usage, ensuring it reliably executes database commands (like `check_stock`) without hallucinating.
3. **Context Window:** Its massive context allows it to remember a customer's order history from weeks ago without "amnesia."

---

## 🏗️ System Architecture

```mermaid
graph TD
    User(["👤 Customer (Telegram)"]) -->|Chat| TAPI["🔵 Telegram Bot API"]
    TAPI -->|Webhook| API["⚡ FastAPI Backend"]
     
    subgraph "The Brain (Meta AI)"
        API -->|Context + Tools| L4["🧠 Llama 4 Maverick 17B"]
        L4 -->|Reasoning & Reply| API
    end
     
    subgraph "Data Layer"
        API <-->|Read/Write| DB[("🗄️ Database")]
    end
     
    API -->|💰 Payment Alert| Owner(["👨‍🍳 Vendor (Admin Chat)"])
    Owner -->|'CONFIRM' cmd| API
    API -->|✅ Receipt| User

    classDef meta fill:#0081FB,stroke:#fff,color:#fff;
    classDef tele fill:#2CA5E0,stroke:#fff,color:#fff;
    class L4 meta;
    class TAPI tele;

```

##✨ Features###1. Bilingual "Code-Switching"Auntie Chioma doesn't just translate; she adapts culturally.

* **Standard Mode:** "Welcome! Our menu features Jollof Rice at N500."
* **Pidgin Mode:** "Ah my customer! Jollof dey ground, N500 per spoon. You go chop?"

###2. Fraud-Proof "Human-in-the-Loop" PaymentWe solve the "Fake Transfer" problem without slowing down the vendor.

1. Customer claims "PAID".
2. Llama 4 extracts the Account Name and Order ID.
3. System alerts the Vendor on Telegram: "💰 Order #105 Paid by Emeka. Confirm?"
4. Vendor taps CONFIRM to release the order.

###3. Dynamic "Chat-Ops" InventoryVendors manage their shop directly inside Telegram.

* `ADD Rice 500` -> Updates the live menu.
* `OUT Chicken` -> Instantly stops the AI from selling chicken.

---

##🛠️ Installation###Prerequisites* Python 3.10+
* Telegram Bot Token (via @BotFather)
* Access to Llama 4 Maverick (via Groq/Together/HuggingFace)

###Quick Start**1. Clone & Install**

```bash
git clone [https://github.com/your-username/bukka-ai.git](https://github.com/your-username/bukka-ai.git)
pip install -r requirements.txt

```

**2. Configure Environment (.env)**

```env
TELEGRAM_BOT_TOKEN=12345:YourTokenHere
DATABASE_URL=postgresql://user:pass@localhost/bukka
LLAMA_API_KEY=gsk_...
OWNER_ID=123456789

```

**3. Run Migrations**

```bash
alembic upgrade head

```

**4. Launch**

```bash
uvicorn main:app --reload

```

```


