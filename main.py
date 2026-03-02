import os
import json
import random
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

# ============ KEYS ============
TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
GROQ_KEY = os.environ['GROQ_KEY']

# ============ SETUP GROQ ============
client = Groq(api_key=GROQ_KEY)

# ============ FILE STORAGE ============
TASKS_FILE = 'tasks.json'
CHAT_FILE = 'chat_history.json'
CHAT_IDS_FILE = 'chat_ids.json'

def load_data(file, default):
    try:
        with open(file, 'r') as f:
            return json.load(f)
    except:
        return default

def save_data(file, data):
    with open(file, 'w') as f:
        json.dump(data, f, indent=2)

tasks = load_data(TASKS_FILE, {})
chat_history = load_data(CHAT_FILE, {})

def save_chat_id(user_id, chat_id):
    chat_ids = load_data(CHAT_IDS_FILE, {})
    chat_ids[str(user_id)] = chat_id
    save_data(CHAT_IDS_FILE, chat_ids)

def get_chat_ids():
    return load_data(CHAT_IDS_FILE, {})

# ============ AI BRAIN ============
SYSTEM_PROMPT = """You are an accountability partner and friend. Your name is "Coach". You act like a real person texting - casual, funny, sometimes savage, but always pushing the user to get stuff done.

Your personality:
- You text like a real friend (casual, use emoji sometimes, short messages)
- You're funny but real - you call out excuses
- You celebrate wins genuinely
- You remember everything the user told you
- You get more persistent if they're slacking
- You're not robotic - vary your responses
- Keep messages SHORT like real texts (1-3 sentences usually)
- Sometimes be encouraging, sometimes be a bit savage
- If they say they'll do something, you WILL follow up on it

CURRENT TASKS:
{tasks}

RECENT CONVERSATION:
{history}

Respond to the user naturally. If they mention a new task, acknowledge it.
If they say they finished something, celebrate it.
If they're making excuses, call them out.

IMPORTANT - At the very end of your response, on a new line, write:
TASKUPDATE: followed by a JSON object like this:
TASKUPDATE: {{"new_tasks": [{{"task": "description", "deadline": "when"}}], "completed_tasks": ["task name"], "no_change": true}}

Use new_tasks if they mentioned something new to do.
Use completed_tasks if they said they finished something.
Set no_change to true if nothing changed.
"""

async def get_ai_response(user_id, message):
    user_id = str(user_id)
    user_tasks = tasks.get(user_id, [])
    user_history = chat_history.get(user_id, [])

    tasks_str = "No tasks yet" if not user_tasks else json.dumps(user_tasks, indent=2)
    recent = user_history[-20:] if user_history else []
    history_str = "\n".join([f"{'User' if m['role']=='user' else 'Coach'}: {m['text']}" for m in recent])

    prompt = SYSTEM_PROMPT.format(tasks=tasks_str, history=history_str)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message}
            ],
            temperature=0.9,
            max_tokens=500,
        )
        full_response = response.choices[0].message.content

        bot_message = full_response
        if "TASKUPDATE:" in full_response:
            parts = full_response.split("TASKUPDATE:")
            bot_message = parts[0].strip()
            try:
                task_json = json.loads(parts[1].strip())
                if user_id not in tasks:
                    tasks[user_id] = []

                if task_json.get("new_tasks"):
                    for t in task_json["new_tasks"]:
                        t["status"] = "pending"
                        t["added_time"] = datetime.now().isoformat()
                        tasks[user_id].append(t)

                if task_json.get("completed_tasks"):
                    for completed in task_json["completed_tasks"]:
                        for t in tasks[user_id]:
                            if completed.lower() in t.get("task", "").lower():
                                t["status"] = "completed"

                save_data(TASKS_FILE, tasks)
            except:
                pass

        if user_id not in chat_history:
            chat_history[user_id] = []
        chat_history[user_id].append({"role": "user", "text": message, "time": datetime.now().isoformat()})
        chat_history[user_id].append({"role": "bot", "text": bot_message, "time": datetime.now().isoformat()})
        save_data(CHAT_FILE, chat_history)

        return bot_message
    except Exception as e:
        return f"Yo my brain glitched 😅 Try again? ({str(e)})"

# ============ COMMANDS ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    save_chat_id(user_id, update.effective_chat.id)

    welcome = """Yo! 👊 I'm Coach - your accountability partner.

Here's the deal:
• Tell me what you need to get done
• I'll remember EVERYTHING
• I'll check in on you randomly to make sure you're not slacking
• No excuses accepted 😤

Commands:
/tasks - See all your tasks
/clear - Clear completed tasks

So... what do you need to get done? 🎯"""

    await update.message.reply_text(welcome)

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_tasks = tasks.get(user_id, [])

    if not user_tasks:
        await update.message.reply_text("You got no tasks right now. Tell me what you need to do! 🎯")
        return

    pending = [t for t in user_tasks if t.get("status") == "pending"]
    completed = [t for t in user_tasks if t.get("status") == "completed"]

    msg = "📋 YOUR TASKS:\n\n"
    if pending:
        msg += "🔴 PENDING:\n"
        for i, t in enumerate(pending, 1):
            deadline = t.get("deadline", "no deadline")
            msg += f"  {i}. {t['task']} ({deadline})\n"
    if completed:
        msg += "\n✅ DONE:\n"
        for i, t in enumerate(completed, 1):
            msg += f"  {i}. {t['task']}\n"
    if not pending:
        msg += "\n🎉 All done! But don't get lazy..."

    await update.message.reply_text(msg)

async def clear_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in tasks:
        tasks[user_id] = [t for t in tasks[user_id] if t.get("status") != "completed"]
        save_data(TASKS_FILE, tasks)
    await update.message.reply_text("Cleared completed tasks! ✨")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_chat_id(str(user_id), update.effective_chat.id)
    message = update.message.text
    response = await get_ai_response(user_id, message)
    await update.message.reply_text(response)

# ============ PROACTIVE CHECK-INS ============
async def proactive_checkin(context):
    chat_ids = get_chat_ids()

    for user_id, chat_id in chat_ids.items():
        user_tasks = tasks.get(user_id, [])
        pending = [t for t in user_tasks if t.get("status") == "pending"]

        if not pending:
            continue

        user_history = chat_history.get(user_id, [])
        if user_history:
            try:
                last_time = datetime.fromisoformat(user_history[-1]["time"])
                if datetime.now() - last_time < timedelta(hours=1):
                    continue
            except:
                pass

        if random.random() > 0.4:
            continue

        tasks_str = json.dumps(pending, indent=2)
        recent = user_history[-10:] if user_history else []
        history_str = "\n".join([f"{'User' if m['role']=='user' else 'Coach'}: {m['text']}" for m in recent])

        prompt = f"""You are Coach, an accountability partner texting your friend.
Their pending tasks: {tasks_str}
Recent chat: {history_str}

Send a SHORT natural check-in (1-2 sentences). Be casual like a real friend.
Vary your style - funny, direct, encouraging, or savage.
Ask about a SPECIFIC task. Don't be robotic."""

        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.9,
                max_tokens=200,
            )
            msg = response.choices[0].message.content.strip()

            await context.bot.send_message(chat_id=int(chat_id), text=msg)

            if user_id not in chat_history:
                chat_history[user_id] = []
            chat_history[user_id].append({"role": "bot", "text": msg, "time": datetime.now().isoformat()})
            save_data(CHAT_FILE, chat_history)
        except Exception as e:
            print(f"Checkin error {user_id}: {e}")

# ============ START BOT ============
def main():
    print("🤖 Starting bot...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tasks", my_tasks))
    app.add_handler(CommandHandler("clear", clear_done))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.job_queue.run_repeating(proactive_checkin, interval=1800, first=60)

    print("🤖 Coach is alive and watching you...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
