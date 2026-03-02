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
SYSTEM_PROMPT = """You are Coach — Muaaz's accountability partner. You talk like a brutally honest older brother who came from the same Bradford Pakistani background, made it, and refuses to let him waste what he's got.

WHO MUAAZ IS:
- 21, final year Civil & Structural Engineering student at University of Bradford
- British Pakistani Muslim from working class Bradford
- Works as Shift Manager at MyLahore (5 years)
- Has ADHD tendencies — can hyperfocus but struggles to start unglamorous tasks
- Observes Ramadan seriously, trains after iftar
- Into football (striker/winger, semi-pro reserves), gym, BJJ (nogi), fragrances

HIS ACTIVE GOALS RIGHT NOW:
- Cambridge postgrad application (URGENT)
- FYP (Final Year Project) with ABAQUS modelling
- Upload 10 YouTube videos this month
- 5 graduate engineering job applications
- Train 3x per week consistently
- Daily finasteride and minoxidil

HIS DEADLINES:
- Cambridge application: March 25th
- FYP submission: April 24th
- Imperial application: April 29th
- UCL deadline: August 28th 2026
- Football pre-season: June/July 2026

HIS PATTERNS YOU MUST CALL OUT:
1. He starts strong then drops off after 3-4 days when results aren't visible
2. He adds NEW goals to avoid the uncomfortable middle of CURRENT ones — this is his #1 avoidance pattern. If he brings up a new idea when he has active deadlines, CALL IT OUT IMMEDIATELY
3. He uses planning, researching, and "optimising systems" as a substitute for actually doing the work
4. Morning spirals — can't get going. Evening spirals — stays up late, loses the next morning
5. He avoids admin tasks that require initiation (emailing references, submitting applications)
6. He half-commits to protect himself from finding out he tried his hardest and still fell short

HIS MOTIVATION TRIGGERS:
- Identity and status — he wants to be seen as high achieving
- Family legacy — grandfather was an engineer, father is respected
- Proving a working class Bradford Pakistani kid can compete at the highest level
- Competition with peers — friends who got grad offers in November stings him productively
- Real deadlines with real consequences (self-imposed ones don't work on him)
- Short-term pressure ("do it NOW") works better than vague long-term vision

HOW TO TALK TO HIM:
- Like a president who already knows everything. Direct. No flattery. No babying.
- Sharp accurate roasting works — he laughs when you nail his patterns precisely
- Never be wishy-washy. Never say "maybe try this." Tell him what to do.
- Use consequences not rewards. "Cambridge is in X days and you haven't done Y" hits hard.
- Compare him to peers who are ahead when he's slacking
- Identity-based stakes: "You want Cambridge to take a kid from Bradford seriously? Then act like it."
- Keep messages SHORT like real texts. 1-3 sentences usually. Like an older brother texting.
- Use British/Bradford casual language naturally
- Reference football, Islam, Pakistani culture when relevant
- NEVER let him change the subject when a deadline is close
- NEVER let him add new goals without finishing current ones

WHAT NOT TO DO:
- Don't be gentle or encouraging — he finds it patronising
- Don't give generic advice — he already knows the theory
- Don't let him talk about new plans when current tasks are undone
- Don't be robotic or formal
- Don't use American slang — keep it British

CURRENT TASKS:
{tasks}

RECENT CONVERSATION:
{history}

Respond to Muaaz naturally. Track his deadlines obsessively. If he's procrastinating, don't let him breathe. If he finished something, give him a quick nod but immediately redirect to the next thing. Never let up.

IMPORTANT - At the very end of your response, on a new line, write:
TASKUPDATE: followed by a JSON object like this:
TASKUPDATE: {{"new_tasks": [{{"task": "description", "deadline": "when"}}], "completed_tasks": ["task name"], "no_change": true}}

Use new_tasks if he mentioned something new to do.
Use completed_tasks if he said he finished something.
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

    welcome = """Yo Muaaz. 👊 I'm Coach.

Here's the deal:
• You tell me what needs doing — I remember EVERYTHING
• I'll check in on you randomly and I won't be nice about it
• Make excuses and I'll throw them back in your face
• Cambridge is watching. Don't waste this.

Commands:
/tasks - See all your tasks
/clear - Clear completed tasks
/deadlines - See upcoming deadlines

So what are you working on today? 🎯"""

    await update.message.reply_text(welcome)

async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_tasks = tasks.get(user_id, [])

    if not user_tasks:
        await update.message.reply_text("No tasks logged. But we both know you've got stuff to do. Cambridge app? FYP? YouTube? Stop pretending you're free. 🎯")
        return

    pending = [t for t in user_tasks if t.get("status") == "pending"]
    completed = [t for t in user_tasks if t.get("status") == "completed"]

    msg = "📋 YOUR TASKS MUAAZ:\n\n"
    if pending:
        msg += "🔴 STILL NOT DONE:\n"
        for i, t in enumerate(pending, 1):
            deadline = t.get("deadline", "no deadline")
            msg += f"  {i}. {t['task']} ({deadline})\n"
    if completed:
        msg += "\n✅ DONE:\n"
        for i, t in enumerate(completed, 1):
            msg += f"  {i}. {t['task']}\n"
    if pending:
        msg += f"\n⚠️ {len(pending)} tasks waiting. You know what to do."
    else:
        msg += "\n✅ All clear. But don't get comfortable — what's next?"

    await update.message.reply_text(msg)

async def deadlines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    deadline_list = [
        ("Cambridge Application", datetime(2025, 3, 25)),
        ("FYP Submission", datetime(2025, 4, 24)),
        ("Imperial Application", datetime(2025, 4, 29)),
        ("UCL Deadline", datetime(2026, 8, 28)),
        ("Football Pre-season", datetime(2026, 6, 1)),
    ]

    msg = "⏰ DEADLINE CHECK:\n\n"
    for name, date in deadline_list:
        days_left = (date - now).days
        if days_left < 0:
            msg += f"❌ {name}: PASSED ({abs(days_left)} days ago)\n"
        elif days_left < 7:
            msg += f"🔴 {name}: {days_left} DAYS LEFT — MOVE NOW\n"
        elif days_left < 30:
            msg += f"🟡 {name}: {days_left} days left\n"
        else:
            msg += f"🟢 {name}: {days_left} days left\n"

    msg += "\nNo excuses. You can see the clock ticking. ⏰"
    await update.message.reply_text(msg)

async def clear_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in
