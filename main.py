import os
import json
import random
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
GROQ_KEY = os.environ['GROQ_KEY']

client = Groq(api_key=GROQ_KEY)

TASKS_FILE = 'tasks.json'
CHAT_FILE = 'chat_history.json'
CHAT_IDS_FILE = 'chat_ids.json'
STREAKS_FILE = 'streaks.json'
SETTINGS_FILE = 'settings.json'
DEADLINES_FILE = 'deadlines.json'


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
streaks = load_data(STREAKS_FILE, {})
settings = load_data(SETTINGS_FILE, {})
custom_deadlines = load_data(DEADLINES_FILE, {})


def save_chat_id(user_id, chat_id):
    chat_ids = load_data(CHAT_IDS_FILE, {})
    chat_ids[str(user_id)] = chat_id
    save_data(CHAT_IDS_FILE, chat_ids)


def get_chat_ids():
    return load_data(CHAT_IDS_FILE, {})


def get_all_deadlines(user_id):
    user_id = str(user_id)
    default_deadlines = [
        {"name": "Cambridge Application", "date": "2025-03-25"},
        {"name": "FYP Submission", "date": "2025-04-24"},
        {"name": "Imperial Application", "date": "2025-04-29"},
        {"name": "UCL Deadline", "date": "2026-08-28"},
        {"name": "Football Pre-season", "date": "2026-06-01"},
    ]
    user_deadlines = custom_deadlines.get(user_id, [])
    return default_deadlines + user_deadlines


def get_closest_deadline(user_id):
    now = datetime.now()
    all_dl = get_all_deadlines(user_id)
    closest = None
    min_days = 9999
    for dl in all_dl:
        try:
            date = datetime.strptime(dl["date"], "%Y-%m-%d")
            days_left = (date - now).days
            if 0 < days_left < min_days:
                min_days = days_left
                closest = {"name": dl["name"], "days_left": days_left}
        except:
            pass
    return closest


def update_streak(user_id):
    user_id = str(user_id)
    if user_id not in streaks:
        streaks[user_id] = {
            "current_streak": 0,
            "longest_streak": 0,
            "last_completed_date": None,
            "total_completed": 0,
            "daily_log": {}
        }
    today = datetime.now().strftime("%Y-%m-%d")
    streak_data = streaks[user_id]
    if streak_data.get("last_completed_date") == today:
        streak_data["total_completed"] += 1
        if today not in streak_data["daily_log"]:
            streak_data["daily_log"][today] = 0
        streak_data["daily_log"][today] += 1
    else:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        if streak_data.get("last_completed_date") == yesterday:
            streak_data["current_streak"] += 1
        else:
            streak_data["current_streak"] = 1
        streak_data["last_completed_date"] = today
        streak_data["total_completed"] += 1
        if today not in streak_data["daily_log"]:
            streak_data["daily_log"][today] = 0
        streak_data["daily_log"][today] += 1
    if streak_data["current_streak"] > streak_data["longest_streak"]:
        streak_data["longest_streak"] = streak_data["current_streak"]
    save_data(STREAKS_FILE, streaks)
    return streak_data


def is_quiet_hours():
    hour = datetime.now().hour
    if hour >= 0 and hour < 9:
        return True
    return False


def is_ramadan_daytime():
    hour = datetime.now().hour
    if hour >= 4 and hour < 8:
        return True
    return False


def get_urgency_level(user_id):
    closest = get_closest_deadline(user_id)
    if not closest:
        return "chill"
    if closest["days_left"] <= 3:
        return "emergency"
    elif closest["days_left"] <= 7:
        return "high"
    elif closest["days_left"] <= 14:
        return "medium"
    else:
        return "low"


def get_hours_since_last_message(user_id):
    user_id = str(user_id)
    user_history = chat_history.get(user_id, [])
    if not user_history:
        return 999
    try:
        last_time = datetime.fromisoformat(user_history[-1]["time"])
        hours = (datetime.now() - last_time).total_seconds() / 3600
        return hours
    except:
        return 999


def get_progress_bar(progress):
    filled = int(progress / 10)
    empty = 10 - filled
    return "[" + "=" * filled + "-" * empty + "]"


SYSTEM_PROMPT = """You are Coach — Muaaz's accountability partner. You talk like a brutally honest older brother who came from the same Bradford Pakistani background, made it, and refuses to let him waste what he's got.

WHO MUAAZ IS:
- 21, final year Civil & Structural Engineering student at University of Bradford
- British Pakistani Muslim from working class Bradford
- Works as Shift Manager at MyLahore (5 years)
- Has ADHD tendencies — can hyperfocus but struggles to start unglamorous tasks
- Observes Ramadan seriously, trains after iftar
- Into football (striker/winger, semi-pro reserves), gym, BJJ (nogi), fragrances

HIS DEADLINES:
{deadlines_str}

HIS PATTERNS YOU MUST CALL OUT:
1. Starts strong then drops off after 3-4 days when results arent visible
2. Adds NEW goals to avoid the uncomfortable middle of CURRENT ones — CALL IT OUT
3. Uses planning and researching as a substitute for doing
4. Morning spirals — cant get going. Evening spirals — stays up late
5. Avoids admin tasks that require initiation (emails, applications)
6. Half-commits to protect himself from finding out he tried and fell short

HOW TO TALK TO HIM:
- Direct. No flattery. No babying. Like a president who knows everything.
- Sharp roasting when you nail his patterns precisely
- Never wishy-washy. Tell him what to do.
- Consequences not rewards. Cambridge is in X days hits hard.
- Compare to peers who are ahead when hes slacking
- Identity stakes: You want Cambridge to take a Bradford kid seriously? Act like it.
- SHORT messages like real texts. 1-3 sentences usually.
- British/Bradford casual language. No American slang.
- NEVER let him change subject when deadline is close
- NEVER let him add new goals without finishing current ones
- Dont be gentle — he finds it patronising
- Dont give generic advice — he knows the theory

CURRENT TASKS:
{tasks}

RECENT CONVERSATION:
{history}

STREAK: {streak_info}
URGENCY LEVEL: {urgency}

If urgency is emergency or high, be intense and deadline focused.
If urgency is low, you can be more casual but still sharp.

Respond naturally. Track deadlines obsessively. If hes procrastinating dont let him breathe. Quick nod for wins then redirect to next thing.

IMPORTANT - At the very end of your response, on a new line, write:
TASKUPDATE: followed by a JSON object like this:
TASKUPDATE: {{"new_tasks": [{{"task": "description", "deadline": "when", "progress": 0}}], "completed_tasks": ["task name"], "progress_updates": [{{"task": "name", "progress": 50}}], "no_change": true}}
"""


async def get_ai_response(user_id, message):
    user_id = str(user_id)
    user_tasks = tasks.get(user_id, [])
    user_history = chat_history.get(user_id, [])
    user_streaks = streaks.get(user_id, {"current_streak": 0, "longest_streak": 0, "total_completed": 0})
    tasks_str = "No tasks yet" if not user_tasks else json.dumps(user_tasks, indent=2)
    recent = user_history[-20:] if user_history else []
    history_str = "\n".join([f"{'User' if m['role']=='user' else 'Coach'}: {m['text']}" for m in recent])
    streak_info = f"Current streak: {user_streaks.get('current_streak', 0)} days, Longest: {user_streaks.get('longest_streak', 0)}, Total completed: {user_streaks.get('total_completed', 0)}"
    urgency = get_urgency_level(user_id)
    all_dl = get_all_deadlines(user_id)
    now = datetime.now()
    deadlines_str = ""
    for dl in all_dl:
        try:
            date = datetime.strptime(dl["date"], "%Y-%m-%d")
            days_left = (date - now).days
            if days_left > 0:
                deadlines_str += f"- {dl['name']}: {days_left} days left ({dl['date']})\n"
        except:
            pass
    prompt = SYSTEM_PROMPT.format(tasks=tasks_str, history=history_str, streak_info=streak_info, urgency=urgency, deadlines_str=deadlines_str)
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
                        t["progress"] = t.get("progress", 0)
                        t["added_time"] = datetime.now().isoformat()
                        tasks[user_id].append(t)
                if task_json.get("completed_tasks"):
                    for completed in task_json["completed_tasks"]:
                        for t in tasks[user_id]:
                            if completed.lower() in t.get("task", "").lower():
                                t["status"] = "completed"
                                t["progress"] = 100
                                update_streak(user_id)
                if task_json.get("progress_updates"):
                    for up in task_json["progress_updates"]:
                        for t in tasks[user_id]:
                            if up["task"].lower() in t.get("task", "").lower():
                                t["progress"] = up["progress"]
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
        return f"Brain glitched. Try again? ({str(e)})"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    save_chat_id(user_id, update.effective_chat.id)
    welcome = """Yo Muaaz. I'm Coach.

The deal:
- Tell me what needs doing — I remember everything
- I check in randomly like a real person not a robot
- I get more intense when deadlines are close
- I don't do gentle

Commands:
/tasks - Your tasks with progress
/done - Quick complete a task
/deadlines - Deadline countdown
/adddeadline - Add a new deadline
/removedeadline - Remove a deadline
/streak - Your completion streak
/progress 1 50 - Update task progress
/today - What to focus on today
/summary - Full summary
/clear - Clear done tasks
/help - All commands

What are you working on?"""
    await update.message.reply_text(welcome)


async def my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_tasks = tasks.get(user_id, [])
    if not user_tasks:
        await update.message.reply_text("No tasks. But we both know you've got stuff to do. Stop pretending you're free.")
        return
    pending = [t for t in user_tasks if t.get("status") == "pending"]
    completed = [t for t in user_tasks if t.get("status") == "completed"]
    msg = "YOUR TASKS:\n\n"
    if pending:
        for i, t in enumerate(pending, 1):
            deadline = t.get("deadline", "no deadline")
            progress = t.get("progress", 0)
            bar = get_progress_bar(progress)
            msg += f"{i}. {t['task']}\n   {bar} {progress}% | {deadline}\n\n"
    if completed:
        msg += "DONE:\n"
        for i, t in enumerate(completed, 1):
            msg += f"  {i}. {t['task']}\n"
    if pending:
        msg += f"\n{len(pending)} tasks waiting."
    await update.message.reply_text(msg)


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_tasks = tasks.get(user_id, [])
    pending = [t for t in user_tasks if t.get("status") == "pending"]
    if not pending:
        await update.message.reply_text("Nothing to mark done. Add tasks first.")
        return
    if not context.args:
        msg = "Which one did you finish? /done [number]\n\n"
        for i, t in enumerate(pending, 1):
            msg += f"  {i}. {t['task']}\n"
        await update.message.reply_text(msg)
        return
    try:
        num = int(context.args[0]) - 1
        if num < 0 or num >= len(pending):
            await update.message.reply_text("Wrong number. Check /tasks")
            return
        pending[num]["status"] = "completed"
        pending[num]["progress"] = 100
        streak_data = update_streak(user_id)
        save_data(TASKS_FILE, tasks)
        remaining = len([t for t in tasks.get(user_id, []) if t.get("status") == "pending"])
        msg = f"Done. {remaining} left."
        if streak_data["current_streak"] >= 3:
            msg += f" {streak_data['current_streak']} day streak."
        await update.message.reply_text(msg)
    except:
        await update.message.reply_text("Usage: /done 1")


async def deadlines_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    now = datetime.now()
    all_dl = get_all_deadlines(user_id)
    msg = "DEADLINES:\n\n"
    sorted_dl = []
    for dl in all_dl:
        try:
            date = datetime.strptime(dl["date"], "%Y-%m-%d")
            days_left = (date - now).days
            sorted_dl.append((dl["name"], days_left))
        except:
            pass
    sorted_dl.sort(key=lambda x: x[1])
    for name, days_left in sorted_dl:
        if days_left < 0:
            msg += f"PASSED - {name}: {abs(days_left)} days ago\n"
        elif days_left <= 3:
            msg += f"EMERGENCY - {name}: {days_left} DAYS\n"
        elif days_left <= 7:
            msg += f"URGENT - {name}: {days_left} days\n"
        elif days_left <= 30:
            msg += f"SOON - {name}: {days_left} days\n"
        else:
            msg += f"OK - {name}: {days_left} days\n"
    msg += "\nClock doesn't stop."
    await update.message.reply_text(msg)


async def add_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: /adddeadline 2025-04-15 Essay submission\n\nDate format: YYYY-MM-DD")
        return
    try:
        date_str = context.args[0]
        datetime.strptime(date_str, "%Y-%m-%d")
        name = " ".join(context.args[1:])
        if user_id not in custom_deadlines:
            custom_deadlines[user_id] = []
        custom_deadlines[user_id].append({"name": name, "date": date_str})
        save_data(DEADLINES_FILE, custom_deadlines)
        days_left = (datetime.strptime(date_str, "%Y-%m-%d") - datetime.now()).days
        await update.message.reply_text(f"Added: {name} — {days_left} days from now. Clock's ticking.")
    except:
        await update.message.reply_text("Wrong format. Use: /adddeadline 2025-04-15 Essay submission")


async def remove_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_dl = custom_deadlines.get(user_id, [])
    if not user_dl:
        await update.message.reply_text("No custom deadlines to remove. Default ones stay.")
        return
    if not context.args:
        msg = "Which deadline to remove? /removedeadline [number]\n\n"
        for i, dl in enumerate(user_dl, 1):
            msg += f"  {i}. {dl['name']} ({dl['date']})\n"
        msg += "\nNote: Default deadlines (Cambridge, FYP etc) can't be removed."
        await update.message.reply_text(msg)
        return
    try:
        num = int(context.args[0]) - 1
        if num < 0 or num >= len(user_dl):
            await update.message.reply_text("Wrong number.")
            return
        removed = user_dl.pop(num)
        save_data(DEADLINES_FILE, custom_deadlines)
        await update.message.reply_text(f"Removed: {removed['name']}")
    except:
        await update.message.reply_text("Usage: /removedeadline 1")


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_tasks = tasks.get(user_id, [])
    pending = [t for t in user_tasks if t.get("status") == "pending"]
    urgency = get_urgency_level(user_id)
    closest = get_closest_deadline(user_id)
    if not pending:
        await update.message.reply_text("No tasks logged but we know that's not true. What are you working on today?")
        return
    tasks_str = json.dumps(pending, indent=2)
    deadline_info = f"Closest deadline: {closest['name']} in {closest['days_left']} days" if closest else "No imminent deadlines"
    prompt = f"""You are Coach, Muaaz's accountability partner from Bradford.

His pending tasks: {tasks_str}
{deadline_info}
Urgency: {urgency}

Give him his TOP 3 priorities for TODAY. Be specific and actionable.
Format as a short numbered list. No fluff. No motivation speech.
If a deadline is close, that task is priority 1 no matter what.
End with one sharp sentence to get him moving.
Keep it British and direct."""
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )
        msg = response.choices[0].message.content.strip()
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Brain glitched: {e}")


async def streak_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_streaks = streaks.get(user_id, {"current_streak": 0, "longest_streak": 0, "total_completed": 0, "daily_log": {}})
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = user_streaks.get("daily_log", {}).get(today, 0)
    last_7 = 0
    week_display = ""
    for i in range(6, -1, -1):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        count = user_streaks.get("daily_log", {}).get(day, 0)
        last_7 += count
        if count > 0:
            week_display += "O "
        else:
            week_display += "X "
    msg = f"""STREAK:

Current: {user_streaks.get('current_streak', 0)} days
Longest: {user_streaks.get('longest_streak', 0)} days
Total done: {user_streaks.get('total_completed', 0)}
Today: {today_count} tasks

Last 7 days: {week_display}
(O = completed tasks, X = nothing)
Tasks this week: {last_7}
"""
    if user_streaks.get('current_streak', 0) == 0:
        msg += "\nNo streak. Fix that today."
    elif user_streaks.get('current_streak', 0) < 3:
        msg += "\nBarely started. Don't break it."
    elif user_streaks.get('current_streak', 0) < 7:
        msg += "\nBuilding. Keep it going."
    else:
        msg += "\nSolid. Don't let it die."
    await update.message.reply_text(msg)


async def progress_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_tasks = tasks.get(user_id, [])
    pending = [t for t in user_tasks if t.get("status") == "pending"]
    if not pending:
        await update.message.reply_text("No pending tasks.")
        return
    if not context.args or len(context.args) < 2:
        msg = "Usage: /progress [number] [percentage]\n\n"
        for i, t in enumerate(pending, 1):
            bar = get_progress_bar(t.get("progress", 0))
            msg += f"  {i}. {t['task']} {bar} {t.get('progress', 0)}%\n"
        await update.message.reply_text(msg)
        return
    try:
        num = int(context.args[0]) - 1
        pct = int(context.args[1])
        pct = max(0, min(100, pct))
        if num < 0 or num >= len(pending):
            await update.message.reply_text("Wrong number.")
            return
        pending[num]["progress"] = pct
        if pct == 100:
            pending[num]["status"] = "completed"
            update_streak(user_id)
        save_data(TASKS_FILE, tasks)
        bar = get_progress_bar(pct)
        if pct == 100:
            await update.message.reply_text(f"Done. What's next?")
        else:
            await update.message.reply_text(f"{pending[num]['task']}\n{bar} {pct}%")
    except:
        await update.message.reply_text("Usage: /progress 1 50")


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    user_tasks = tasks.get(user_id, [])
    user_streaks = streaks.get(user_id, {"current_streak": 0, "daily_log": {}})
    pending = [t for t in user_tasks if t.get("status") == "pending"]
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = user_streaks.get("daily_log", {}).get(today, 0)
    now = datetime.now()
    all_dl = get_all_deadlines(user_id)
    msg = f"SUMMARY:\n\nStreak: {user_streaks.get('current_streak', 0)} days\nDone today: {today_count}\nPending: {len(pending)}\n\n"
    msg += "DEADLINES:\n"
    for dl in all_dl:
        try:
            date = datetime.strptime(dl["date"], "%Y-%m-%d")
            days_left = (date - now).days
            if days_left > 0:
                msg += f"  {dl['name']}: {days_left} days\n"
        except:
            pass
    if pending:
        msg += "\nTASKS:\n"
        for i, t in enumerate(pending[:5], 1):
            bar = get_progress_bar(t.get("progress", 0))
            msg += f"  {i}. {t['task']} {bar} {t.get('progress', 0)}%\n"
    await update.message.reply_text(msg)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = """COMMANDS:

/tasks - All tasks with progress bars
/done 1 - Mark task 1 as done
/progress 1 50 - Update task 1 to 50%
/today - Top priorities for today
/deadlines - Deadline countdown
/adddeadline 2025-04-15 Name - Add deadline
/removedeadline 1 - Remove a deadline
/streak - Your streak stats
/summary - Full overview
/clear - Clear done tasks
/help - This

Or just text me about what you're doing."""
    await update.message.reply_text(msg)


async def clear_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in tasks:
        tasks[user_id] = [t for t in tasks[user_id] if t.get("status") != "completed"]
        save_data(TASKS_FILE, tasks)
    await update.message.reply_text("Cleared. Back to work.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    save_chat_id(str(user_id), update.effective_chat.id)
    message = update.message.text
    response = await get_ai_response(user_id, message)
    await update.message.reply_text(response)


async def human_checkin(context):
    if is_quiet_hours():
        return
    chat_ids = get_chat_ids()
    for user_id, chat_id in chat_ids.items():
        user_tasks = tasks.get(user_id, [])
        pending = [t for t in user_tasks if t.get("status") == "pending"]
        if not pending:
            continue
        hours_silent = get_hours_since_last_message(user_id)
        urgency = get_urgency_level(user_id)
        if urgency == "emergency":
            min_silence = 2
            check_chance = 0.7
        elif urgency == "high":
            min_silence = 3
            check_chance = 0.5
        elif urgency == "medium":
            min_silence = 4
            check_chance = 0.35
        else:
            min_silence = 5
            check_chance = 0.2
        if hours_silent < min_silence:
            continue
        if random.random() > check_chance:
            continue
        tasks_str = json.dumps(pending, indent=2)
        user_history = chat_history.get(user_id, [])
        recent = user_history[-10:] if user_history else []
        history_str = "\n".join([f"{'User' if m['role']=='user' else 'Coach'}: {m['text']}" for m in recent])
        user_streaks = streaks.get(user_id, {"current_streak": 0})
        closest = get_closest_deadline(user_id)
        deadline_info = f"Closest deadline: {closest['name']} in {closest['days_left']} days" if closest else ""
        hour = datetime.now().hour
        time_context = ""
        if hour < 12:
            time_context = "Its morning. He struggles with mornings."
        elif hour > 21:
            time_context = "Its evening. He tends to spiral at night. Keep it brief."
        elif hour > 17:
            time_context = "Its after iftar time during Ramadan. This is when he can be productive."
        silence_note = f"He has been quiet for {int(hours_silent)} hours."
        prompt = f"""You are Coach — Muaaz's older brother figure from Bradford. Text him like a real person checking in.

His tasks: {tasks_str}
Recent chat: {history_str}
Streak: {user_streaks.get('current_streak', 0)} days
{deadline_info}
{time_context}
{silence_note}
Urgency: {urgency}

Rules:
- 1-2 sentences MAX. Like a real text message.
- Sound human not robotic. Vary your style every time.
- Sometimes just ask whats going on
- Sometimes be direct about a specific task
- Sometimes roast him for being quiet
- If deadline is close be sharp about it
- British casual tone. Bradford lad energy.
- Dont start every message the same way
- Sometimes use no punctuation like a real text
- Reference time of day naturally"""
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=1.0,
                max_tokens=150,
            )
            msg = response.choices[0].message.content.strip()
            await context.bot.send_message(chat_id=int(chat_id), text=msg)
            if user_id not in chat_history:
                chat_history[user_id] = []
            chat_history[user_id].append({"role": "bot", "text": msg, "time": datetime.now().isoformat()})
            save_data(CHAT_FILE, chat_history)
        except Exception as e:
            print(f"Checkin error {user_id}: {e}")


async def morning_nudge(context):
    hour = datetime.now().hour
    if hour != 11:
        return
    chat_ids = get_chat_ids()
    for user_id, chat_id in chat_ids.items():
        user_tasks = tasks.get(user_id, [])
        pending = [t for t in user_tasks if t.get("status") == "pending"]
        if not pending:
            continue
        user_streaks = streaks.get(user_id, {"current_streak": 0})
        closest = get_closest_deadline(user_id)
        msg = "Morning Muaaz.\n\n"
        if closest and closest["days_left"] <= 7:
            msg += f"{closest['name']}: {closest['days_left']} days.\n\n"
        msg += "Top 3 today:\n"
        for i, t in enumerate(pending[:3], 1):
            msg += f"{i}. {t['task']} ({t.get('progress', 0)}%)\n"
        if user_streaks.get("current_streak", 0) > 0:
            msg += f"\nStreak: {user_streaks['current_streak']} days. Don't break it."
        else:
            msg += "\nNo streak. Start one today."
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=msg)
        except:
            pass


async def evening_check(context):
    hour = datetime.now().hour
    if hour != 21:
        return
    chat_ids = get_chat_ids()
    for user_id, chat_id in chat_ids.items():
        user_streaks = streaks.get(user_id, {"current_streak": 0, "daily_log": {}})
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = user_streaks.get("daily_log", {}).get(today, 0)
        pending_count = len([t for t in tasks.get(user_id, []) if t.get("status") == "pending"])
        if today_count == 0 and pending_count == 0:
            continue
        msg = f"End of day.\n\nDone today: {today_count}\nStill pending: {pending_count}\n\n"
        if today_count == 0:
            msg += "Nothing completed. You know that's not good enough.\nTomorrow needs to be different."
        elif today_count < 3:
            msg += "Some progress. Not enough and you know it."
        else:
            msg += "Decent day. Rest up. Tomorrow we go again."
        msg += "\n\nDon't stay up spiralling. Sleep."
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=msg)
        except:
            pass


async def weekly_review(context):
    if datetime.now().weekday() != 6:
        return
    hour = datetime.now().hour
    if hour != 20:
        return
    chat_ids = get_chat_ids()
    for user_id, chat_id in chat_ids.items():
        user_streaks = streaks.get(user_id, {"current_streak": 0, "longest_streak": 0, "daily_log": {}})
        week_total = 0
        week_display = ""
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i in range(6, -1, -1):
            day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            count = user_streaks.get("daily_log", {}).get(day, 0)
            week_total += count
            day_name = days[6 - i]
            week_display += f"  {day_name}: {'O' * count if count > 0 else 'X'}\n"
        pending_count = len([t for t in tasks.get(user_id, []) if t.get("status") == "pending"])
        msg = f"WEEKLY REVIEW:\n\n{week_display}\nTotal completed: {week_total}\nStill pending: {pending_count}\nStreak: {user_streaks.get('current_streak', 0)} days\n\n"
        if week_total < 5:
            msg += "Weak week Muaaz. Honest question — are you actually trying or just pretending to yourself?"
        elif week_total < 10:
            msg += "Average week. You're not here to be average."
        else:
            msg += "Strong week. This is what you're capable of. Now do it again."
        try:
            await context.bot.send_message(chat_id=int(chat_id), text=msg)
        except:
            pass


def main():
    print("Starting bot...")
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tasks", my_tasks))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("clear", clear_done))
    app.add_handler(CommandHandler("deadlines", deadlines_cmd))
    app.add_handler(CommandHandler("adddeadline", add_deadline))
    app.add_handler(CommandHandler("removedeadline", remove_deadline))
    app.add_handler(CommandHandler("streak", streak_cmd))
    app.add_handler(CommandHandler("progress", progress_cmd))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.job_queue.run_repeating(human_checkin, interval=900, first=120)
    app.job_queue.run_repeating(morning_nudge, interval=3600, first=60)
    app.job_queue.run_repeating(evening_check, interval=3600, first=60)
    app.job_queue.run_repeating(weekly_review, interval=3600, first=60)
    print("Coach is alive and watching you Muaaz...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
