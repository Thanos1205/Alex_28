import json
import pathlib
import tkinter as tk
from tkinter import ttk
import random
import threading
import time
from PIL import Image, ImageTk
import pygame

# -----------------------------
# GAME DATA
# -----------------------------

def validate_game_data(game_data):
    for cat, questions in game_data.items():
        for idx, question in enumerate(questions, start=1):
            answer = question.get("answer")
            options = question.get("options")
            if options is None or answer is None:
                raise ValueError(
                    f"Kategorie '{cat}', Frage {idx}: 'answer' und 'options' müssen vorhanden sein."
                )
            if answer not in options:
                raise ValueError(
                    f"Kategorie '{cat}', Frage {idx}: Die richtige Antwort '{answer}' fehlt in den Antwortmöglichkeiten."
                )
    return game_data


def load_game_data():
    path = pathlib.Path(__file__).with_name("Fragen.json")
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return validate_game_data(data)
        except Exception as exc:
            raise ValueError(f"Fehler beim Laden von Fragen.json: {exc}")
    else:
        raise FileNotFoundError("Fragen.json not found. Please create the file with the appropriate structure.")

pygame.mixer.init()

game_data = load_game_data()
chatgpt_data = None
user_name = "Alex"

# -----------------------------
# CHATGPT DATA
# -----------------------------

def load_chatgpt_data():
    path = pathlib.Path(__file__).with_name("ChatGPT.json")
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            raise ValueError(f"Fehler beim Laden von ChatGPT.json: {exc}")
    else:
        raise FileNotFoundError("ChatGPT.json not found. Please create the file with the appropriate structure.")

chatgpt_data = load_chatgpt_data()

# -----------------------------
# GAME STATE
# -----------------------------
user_score = 0
ai_score = 0
current_category = None

progress = {
    cat: {
        "index": 0,
        "done": [False] * len(game_data[cat]),
        "answered": 0,
        "failed": False,
        "failed_index": None,
        "user_score": 0,
        "ai_score": 0,
        "shown": [False] * len(game_data[cat]),
        "user_answers": [None] * len(game_data[cat]),
        "ai_answers": [None] * len(game_data[cat]),
    }
    for cat in game_data
}

current_options = []
option_buttons = []
category_buttons = {}
show_answers_used = False
current_question_answered = False
last_action = None
undo_clickable = False

# audio volume state (0.0 - 1.0)
music_volume = 0.2
effects_volume = 0.3

def set_music_volume(val):
    global music_volume
    try:
        music_volume = float(val)
    except Exception:
        music_volume = 0.0
        pygame.mixer.music.set_volume(music_volume)

def set_effects_volume(val):
    global effects_volume
    try:
        effects_volume = float(val)
    except Exception:
        effects_volume = 0.0
    try:
        # update all mixer channels (music uses mixer.music separately)
        num = pygame.mixer.get_num_channels()
        for i in range(num):
            try:
                ch = pygame.mixer.Channel(i)
                ch.set_volume(effects_volume)
            except Exception:
                pass
    except Exception:
        pass

# track active effect channels so we can pause/resume music while effects play
active_effect_channels = 0
music_was_playing = False
_audio_lock = threading.Lock()


def update_undo_button():
    # Undo is enabled only if there is a last action, it was incorrect,
    # and the user hasn't clicked somewhere else since the action.
    try:
        if last_action is not None and last_action.get("correct") is False and undo_clickable:
            undo_button.config(state="normal")
        else:
            undo_button.config(state="disabled")
    except Exception:
        try:
            undo_button.config(state="disabled")
        except Exception:
            pass


def disable_option_buttons():
    for row in option_buttons:
        try:
            row["button"].config(state="disabled")
        except Exception:
            pass


def play_sound(filename):
    # Play short sound effects from the sounds/ folder.
    sounds_dir = pathlib.Path(__file__).with_name("sounds")
    sound_path = sounds_dir / filename
    if not sound_path.exists():
        return
    try:
        sound = pygame.mixer.Sound(str(sound_path))
        try:
            sound.set_volume(effects_volume)
        except Exception:
            pass
        ch = sound.play()
        try:
            # also ensure the playing channel is set to current effects volume
            if ch is not None:
                ch.set_volume(effects_volume)
                # pause music when an effect starts
                with _audio_lock:
                    global active_effect_channels, music_was_playing
                    active_effect_channels += 1
                    try:
                        if pygame.mixer.music.get_busy():
                            pygame.mixer.music.pause()
                            music_was_playing = True
                    except Exception:
                        pass

                # monitor channel in a background thread and resume music when done
                def _monitor(ch_inner):
                    global active_effect_channels, music_was_playing
                    try:
                        while ch_inner.get_busy():
                            time.sleep(0.05)
                    except Exception:
                        pass
                    finally:
                        with _audio_lock:
                            try:
                                active_effect_channels -= 1
                            except Exception:
                                pass
                            if active_effect_channels <= 0:
                                # resume music if it was playing before effects
                                try:
                                    if music_was_playing:
                                        pygame.mixer.music.unpause()
                                except Exception:
                                    pass
                                # reset flag
                                try:
                                    music_was_playing = False
                                except Exception:
                                    pass

                t = threading.Thread(target=_monitor, args=(ch,))
                t.daemon = True
                t.start()
        except Exception:
            pass
    except Exception:
        pass


def start_background_for_category(cat):
    # Load and play background track for a category (looping).
    sounds_dir = pathlib.Path(__file__).with_name("sounds")
    # try exact match first, then case-insensitive search
    candidates = list(sounds_dir.glob(f"{cat}.*"))
    if not candidates:
        # case-insensitive search
        for p in sounds_dir.iterdir():
            if p.is_file() and p.suffix.lower() in (".mp3", ".wav", ".ogg") and p.stem.lower() == cat.lower():
                candidates.append(p)
                break
    if not candidates:
        # fallback to Random.mp3 if present
        fallback = sounds_dir / "Random.mp3"
        if fallback.exists():
            candidates = [fallback]
    if not candidates:
        return

    track = str(candidates[0])
    try:
        # stop any current music and load new track
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
    except Exception:
        pass

    try:
        pygame.mixer.music.load(track)
        try:
            pygame.mixer.music.set_volume(music_volume)
        except Exception:
            pass
        pygame.mixer.music.play(-1)
    except Exception:
        pass


def stop_background():
    try:
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
    except Exception:
        pass


# -----------------------------
# GUI SETUP
# -----------------------------
root = tk.Tk()
root.title("Man vs. Machine Quiz Game - Alex's Birthday Edition")
root.geometry("1600x900")
root.minsize(1200, 750)

# LEFT FRAME (categories)
left_frame = tk.Frame(root, width=300)
left_frame.pack(side="left", fill="y", padx=10, pady=10)
left_frame.pack_propagate(False)

# RIGHT FRAME (game area)
right_frame = tk.Frame(root)
right_frame.pack(side="right", expand=True, fill="both", padx=10, pady=10)

top_bar = tk.Frame(right_frame)
top_bar.pack(fill="x", pady=(0, 10))

right_info_frame = tk.Frame(top_bar, width=280)
right_info_frame.pack(side="right", anchor="n", padx=10)

# center title using a center frame so it's truly centered on wide layouts
center_frame = tk.Frame(top_bar)
center_frame.pack(side="left", fill="both", expand=True)
title = tk.Label(center_frame, text="Select a category", font=("Arial", 18))
title.pack()

score_label = tk.Label(right_info_frame, text="", font=("Arial", 20))
score_label.pack()

chatgpt_icon = None
alex_icon = None
try:
    icon_path = pathlib.Path(__file__).with_name("images") / "ChatGPT.png"
    if icon_path.exists():
            img = Image.open(str(icon_path)).convert("RGBA")
            img = img.resize((64, 64), Image.LANCZOS)
            chatgpt_icon = ImageTk.PhotoImage(img)
except Exception:
    chatgpt_icon = None

try:
    a_path = pathlib.Path(__file__).with_name("images") / "Alex.png"
    if a_path.exists():
        img = Image.open(str(a_path)).convert("RGBA")
        img = img.resize((64, 64), Image.LANCZOS)
        alex_icon = ImageTk.PhotoImage(img)
except Exception:
    alex_icon = None

content_frame = tk.Frame(right_frame)
content_frame.pack(fill="both", expand=True)

question_label = tk.Label(content_frame, text="", wraplength=780, font=("Arial", 16), justify="left")
question_label.pack(pady=10)

answer_entry = tk.Entry(content_frame, font=("Arial", 16), width=40)
answer_entry.pack(pady=8)

result_label = tk.Label(content_frame, text="", font=("Arial", 20))
result_label.pack(pady=8)

# Options container with player/AI icons
options_container = tk.Frame(content_frame)
options_container.pack(pady=10, fill="both", expand=True)

left_img_label = tk.Label(options_container, width=14, height=14)
left_img_label.pack(side="left", padx=10, pady=10)
left_img_label.pack_propagate(False)

# larger option frame, no border
option_frame = tk.Frame(options_container, bg=right_frame.cget('bg'))
option_frame.pack(side="left", padx=10, pady=5, expand=True, fill="both")

right_img_label = tk.Label(options_container, width=14, height=14)
right_img_label.pack(side="left", padx=10, pady=10)
right_img_label.pack_propagate(False)

# -----------------------------
# FUNCTIONS
# -----------------------------
def update_score():
    score_label.config(text=f"{user_name}     KI  \n{user_score}   -   {ai_score}")


def update_category_button(cat):
    row_widgets = category_buttons[cat]
    btn = row_widgets["button"]
    score_lbl = row_widgets["score"]
    q_buttons = row_widgets.get("question_buttons", [])
    answered = progress[cat]["answered"]
    total = len(game_data[cat])
    user_cat_score = progress[cat]["user_score"]
    ai_cat_score = progress[cat]["ai_score"]
    btn_text = f"{cat} ({answered}/{total})"
    score_text = f"{user_cat_score}-{ai_cat_score}"

    if progress[cat]["failed"]:
        btn.config(
            text=btn_text,
            bg="#ffcccc",
            activebackground="#ffcccc",
            fg="black",
            state="normal",
        )
    elif answered >= total:
        btn.config(
            text=btn_text,
            bg="#ccffcc",
            activebackground="#ccffcc",
            fg="black",
            state="disabled",
        )
    else:
        btn.config(text=btn_text, bg=btn.default_bg, activebackground=btn.default_bg, fg="black", state="normal")

    score_lbl.config(text=score_text)

    # Update per-question buttons for each category
    current_idx = progress[cat]["index"]
    for q_idx, q_btn in enumerate(q_buttons):
        if not hasattr(q_btn, "default_bg"):
            q_btn.default_bg = q_btn.cget("bg")

        if progress[cat]["failed"]:
            state = "normal"
        elif progress[cat]["done"][q_idx]:
            state = "normal"
        else:
            state = "normal" if q_idx == current_idx else "disabled"

        if progress[cat]["done"][q_idx] and not progress[cat]["failed"]:
            q_btn_bg = "#ccffcc"
        elif progress[cat]["failed"] and q_idx == progress[cat]["failed_index"]:
            q_btn_bg = "#ffcccc"
        else:
            q_btn_bg = q_btn.default_bg

        q_btn.config(state=state, bg=q_btn_bg, activebackground=q_btn_bg)


def update_all_category_buttons():
    for cat in category_buttons:
        update_category_button(cat)


def get_chatgpt_answer(question, cat, idx):
    answers = chatgpt_data.get(cat, []) if isinstance(chatgpt_data, dict) else []
    if idx < len(answers):
        item = answers[idx]
        if item.get("q") == question.get("q"):
            return item.get("answer")
    for item in answers:
        if item.get("q") == question.get("q"):
            return item.get("answer")
    if idx < len(answers):
        return answers[idx].get("answer")
    return None


def load_category(cat):
    global current_category
    current_category = cat
    result_label.config(text="")
    # start background music for this category
    start_background_for_category(cat)
    update_category_button(cat)
    load_question()

def load_review_question(cat, idx):
    global current_category, current_options, current_question_answered

    current_category = cat
    question = game_data[cat][idx]
    current_options = question["options"][:]
    random.shuffle(current_options)
    current_question_answered = False

    title.config(text=f"Category: {cat} (Review)")
    question_label.config(text=f"Q{idx+1}: {question['q']}")
    answer_entry.config(state="disabled")
    submit_button.config(state="disabled")
    next_button.config(state="disabled")
    show_button.config(state="disabled")

    render_option_buttons(disabled=True, mark_shown=False)
    _update_row_icons(progress[cat]["user_answers"][idx], progress[cat]["ai_answers"][idx])
    _highlight_options(progress[cat]["user_answers"][idx], progress[cat]["ai_answers"][idx], question["answer"])
    update_undo_button()
    update_category_button(cat)


def get_current_question():
    cat = current_category
    idx = progress[cat]["index"]

    # skip completed questions
    while idx < len(game_data[cat]) and progress[cat]["done"][idx]:
        idx += 1
        progress[cat]["index"] = idx

    if idx >= len(game_data[cat]):
        return None, None

    return game_data[cat][idx], idx

def load_question():
    global current_options, show_answers_used, current_question_answered

    if not current_category:
        return

    if progress[current_category]["failed"]:
        failed_index = progress[current_category]["failed_index"]
        if failed_index is None or failed_index >= len(game_data[current_category]):
            question_label.config(text=f"❌ {current_category} failed. Cannot continue.")
            title.config(text=f"Category: {current_category}")
            answer_entry.config(state="disabled")
            submit_button.config(state="disabled")
            next_button.config(state="disabled")
            show_button.config(state="disabled")
            update_undo_button()
            disable_option_buttons()
            return

        question = game_data[current_category][failed_index]
        current_options = question["options"][:]
        random.shuffle(current_options)

        title.config(text=f"Category: {current_category}")
        question_label.config(text=f"❌ {current_category} failed on Q{failed_index+1}: {question['q']}")
        answer_entry.config(state="disabled")
        submit_button.config(state="disabled")
        next_button.config(state="disabled")
        show_button.config(state="disabled")
        update_undo_button()

        for widget in option_frame.winfo_children():
            widget.destroy()
        option_buttons.clear()
        for opt in current_options:
            row = tk.Frame(option_frame, bg=option_frame.cget("bg"), height=72)
            row.pack_propagate(False)
            left_icon_frame = tk.Frame(row, width=90, height=90, bg=option_frame.cget("bg"))
            left_icon_frame.pack_propagate(False)
            user_icon_label = tk.Label(left_icon_frame, image="", bg=option_frame.cget("bg"))
            user_icon_label.pack(expand=True)
            btn = tk.Button(row, text=opt, width=32, height=2, font=("Arial", 12), state="disabled", anchor="w", padx=8)
            btn.default_bg = btn.cget("bg")
            right_icon_frame = tk.Frame(row, width=90, height=90, bg=option_frame.cget("bg"))
            right_icon_frame.pack_propagate(False)
            ai_icon_label = tk.Label(right_icon_frame, image="", bg=option_frame.cget("bg"))
            ai_icon_label.pack(expand=True)
            left_icon_frame.pack(side="left", padx=(0, 4), pady=3)
            btn.pack(side="left", fill="x", expand=True, pady=3)
            right_icon_frame.pack(side="left", padx=(4, 0), pady=3)
            row.pack(fill="x", pady=3, padx=6)
            option_buttons.append({
                "text": opt,
                "button": btn,
                "user_icon": user_icon_label,
                "ai_icon": ai_icon_label,
            })

        # restore answer icons for the failed question when reloading the category
        _update_row_icons(
            progress[current_category]["user_answers"][failed_index],
            progress[current_category]["ai_answers"][failed_index],
        )
        _highlight_options(
            progress[current_category]["user_answers"][failed_index],
            progress[current_category]["ai_answers"][failed_index],
            question["answer"],
        )
        return

    question, idx = get_current_question()

    if question is None:
        option_buttons.clear()
        for widget in option_frame.winfo_children():
            widget.destroy()
        answer_entry.config(state="disabled")
        submit_button.config(state="disabled")
        next_button.config(state="disabled")
        show_button.config(state="disabled")
        question_label.config(text=f"✅ {current_category} completed!")
        title.config(text=f"Category: {current_category}")
        return

    current_options = question["options"][:]
    random.shuffle(current_options)
    current_question_answered = False

    option_buttons.clear()
    for widget in option_frame.winfo_children():
        widget.destroy()

    answer_entry.config(state="normal")
    answer_entry.delete(0, tk.END)
    result_label.config(text="")
    submit_button.config(state="normal")
    next_button.config(state="disabled")
    show_button.config(state="normal")
    update_undo_button()

    title.config(text=f"Category: {current_category}")
    question_label.config(text=f"Q{idx+1}: {question['q']}")
    try:
        question_label.config(fg="black")
    except Exception:
        pass
    try:
        left_img_label.config(image="")
        left_img_label.image = None
    except Exception:
        pass
    try:
        right_img_label.config(image="")
        right_img_label.image = None
    except Exception:
        pass

    show_answers_used = progress[current_category]["shown"][idx]
    if show_answers_used:
        render_option_buttons(disabled=False, mark_shown=False)

def render_option_buttons(disabled=False, mark_shown=False, show_idx=None):
    global show_answers_used

    if not current_category:
        return

    if mark_shown and show_idx is not None:
        show_answers_used = True
        progress[current_category]["shown"][show_idx] = True
    elif mark_shown:
        question, idx = get_current_question()
        if question is not None:
            show_answers_used = True
            progress[current_category]["shown"][idx] = True

    for widget in option_frame.winfo_children():
        widget.destroy()

    option_buttons.clear()
    for opt in current_options:
        row = tk.Frame(option_frame, bg=option_frame.cget("bg"), height=72)
        row.pack_propagate(False)
        left_icon_frame = tk.Frame(row, width=90, height=90, bg=option_frame.cget("bg"))
        left_icon_frame.pack_propagate(False)
        user_icon_label = tk.Label(left_icon_frame, image="", bg=option_frame.cget("bg"))
        user_icon_label.pack(expand=True)
        btn = tk.Button(row, text=opt, width=32, height=2, font=("Arial", 12),
                        command=lambda o=opt: select_option(o), anchor="w", padx=8)
        btn.default_bg = btn.cget("bg")
        if disabled:
            btn.config(state="disabled")
        right_icon_frame = tk.Frame(row, width=90, height=90, bg=option_frame.cget("bg"))
        right_icon_frame.pack_propagate(False)
        ai_icon_label = tk.Label(right_icon_frame, image="", bg=option_frame.cget("bg"))
        ai_icon_label.pack(expand=True)
        left_icon_frame.pack(side="left", padx=(0, 4), pady=3)
        btn.pack(side="left", fill="x", expand=True, pady=3)
        right_icon_frame.pack(side="left", padx=(4, 0), pady=3)
        row.pack(fill="x", pady=3, padx=6)
        option_buttons.append({
            "text": opt,
            "button": btn,
            "user_icon": user_icon_label,
            "ai_icon": ai_icon_label,
        })

def _highlight_options(user_ans, ai_ans, correct_ans):
    # color mapping: correct -> green, user wrong -> red, ai wrong -> orange
    for row in option_buttons:
        btn = row["button"]
        try:
            btn.config(bg=btn.default_bg)
        except Exception:
            try:
                btn.config(bg="SystemButtonFace")
            except Exception:
                pass

    # mark correct
    for row in option_buttons:
        if row["text"].strip().lower() == correct_ans.strip().lower():
            try:
                row["button"].config(bg="#ccffcc")
            except Exception:
                pass
            break

    # mark user's wrong answer
    if user_ans and user_ans.strip().lower() != correct_ans.strip().lower():
        for row in option_buttons:
            if row["text"].strip().lower() == user_ans.strip().lower():
                try:
                    row["button"].config(bg="#ffcccc")
                except Exception:
                    pass
                break

    # mark AI's wrong answer (if different)
    if ai_ans and ai_ans.strip().lower() != correct_ans.strip().lower() and (not user_ans or ai_ans.strip().lower() != user_ans.strip().lower()):
        for row in option_buttons:
            if row["text"].strip().lower() == ai_ans.strip().lower():
                try:
                    row["button"].config(bg="#ffdca3")
                except Exception:
                    pass
                break

def _update_row_icons(user_ans, ai_ans):
    # clear any old icons first
    for row in option_buttons:
        try:
            row["user_icon"].config(image="")
            row["user_icon"].image = None
        except Exception:
            pass
        try:
            row["ai_icon"].config(image="")
            row["ai_icon"].image = None
        except Exception:
            pass

    for row in option_buttons:
        text = row["text"].strip().lower()
        if user_ans and text == user_ans.strip().lower() and alex_icon is not None:
            try:
                row["user_icon"].config(image=alex_icon)
                row["user_icon"].image = alex_icon
            except Exception:
                pass
        if ai_ans and text == ai_ans.strip().lower() and chatgpt_icon is not None:
            try:
                row["ai_icon"].config(image=chatgpt_icon)
                row["ai_icon"].image = chatgpt_icon
            except Exception:
                pass


def select_option(opt):
    answer_entry.config(state="normal")
    answer_entry.delete(0, tk.END)
    answer_entry.insert(0, opt)
    disable_option_buttons()
    submit("options")


def load_category_question(cat, q_idx):
    if progress[cat]["failed"]:
        load_review_question(cat, q_idx)
        return

    if q_idx < progress[cat]["index"] and progress[cat]["done"][q_idx]:
        load_review_question(cat, q_idx)
        return

    if q_idx == progress[cat]["index"]:
        load_category(cat)
        return

    # future questions remain locked until their turn
    return


def show_options():
    if not current_category or progress[current_category]["failed"]:
        return

    question, idx = get_current_question()
    render_option_buttons(disabled=False, mark_shown=True, show_idx=idx)


def next_question():
    if not current_category:
        return

    load_question()


def undo_last_question():
    global user_score, ai_score, current_question_answered, last_action, current_category

    if last_action is None:
        return

    cat = last_action["category"]
    idx = last_action["idx"]
    user_points = last_action.get("user_points", 0)
    ai_points = last_action.get("ai_points", 0)
    previous_failed = last_action["previous_failed"]
    previous_failed_index = last_action["previous_failed_index"]

    user_score -= user_points
    ai_score -= ai_points
    progress[cat]["user_score"] -= user_points
    progress[cat]["ai_score"] -= ai_points

    progress[cat]["done"][idx] = False
    progress[cat]["answered"] -= 1
    progress[cat]["index"] = idx
    progress[cat]["failed"] = previous_failed
    progress[cat]["failed_index"] = previous_failed_index

    current_category = cat
    current_question_answered = False
    last_action = None
    start_background_for_category(cat)
    update_undo_button()
    load_question()
    update_category_button(cat)
    # ensure displayed scores are updated after undo
    try:
        update_score()
    except Exception:
        pass


undo_button = tk.Button(right_info_frame, text="Undo letzte Frage",
                        command=undo_last_question, font=("Arial", 12), width=18, state="disabled")
undo_button.pack(pady=5)


def submit(mode):
    global user_score, ai_score, current_question_answered, last_action, undo_clickable

    if not current_category or progress[current_category]["failed"]:
        return

    question, idx = get_current_question()
    if not question:
        return

    if current_question_answered:
        return

    user = answer_entry.get().strip()
    if not user:
        result_label.config(text="Bitte Antwort eingeben.")
        return

    correct = question["answer"]
    previous_failed = progress[current_category]["failed"]
    previous_failed_index = progress[current_category]["failed_index"]

    ai_answer = get_chatgpt_answer(question, current_category, idx)
    ai_points = 0
    additional_ai = 0
    user_points = 0

    if user.lower() == correct.lower():
        if mode == "submit":
            user_points = 2 if not show_answers_used else 1
        else:
            user_points = 1
        user_score += user_points
        result_text = f"{user_name}: +{user_points}"
        play_sound("answer right.mp3")
        try:
            question_label.config(fg="green")
        except Exception:
            pass
        correct_answer = True
    else:
        user_points = 0
        result_text = f"{user_name}: +{user_points}"  # f"Wrong! Answer: {correct}"
        progress[current_category]["failed"] = True
        progress[current_category]["failed_index"] = idx
        play_sound("answer wrong.mp3")
        try:
            question_label.config(fg="red")
        except Exception:
            pass
        correct_answer = False

        # User failed this question — assign AI answers/points for any
        # unanswered questions in this category so we can show what ChatGPT
        # would have answered and award points accordingly.
        try:
            cat = current_category
            total_q = len(game_data[cat])
            for j in range(total_q):
                # skip if AI answer already recorded
                if progress[cat]["ai_answers"][j] is not None:
                    continue
                q = game_data[cat][j]
                ai_ans_j = get_chatgpt_answer(q, cat, j)
                progress[cat]["ai_answers"][j] = ai_ans_j
                if ai_ans_j and ai_ans_j.strip().lower() == q["answer"].strip().lower():
                    additional_ai += 1
            # Don't add to progress/ai_score here; will do it once at the end
            # along with current question's AI point
        except Exception:
            additional_ai = 0

    progress[current_category]["user_answers"][idx] = user
    progress[current_category]["ai_answers"][idx] = ai_answer

    # Check if AI answered the current question correctly
    ai_correct_current = (ai_answer is not None and ai_answer.strip().lower() == correct.strip().lower())
    ai_points_current = 1 if ai_correct_current else 0

    # Calculate total AI points for this action
    # If user failed: additional_ai (from other questions) + ai_points_current (from this question)
    # If user correct: only ai_points_current (from this question)
    if not correct_answer:
        ai_points = additional_ai + ai_points_current
    else:
        ai_points = ai_points_current

    # Add to global score
    ai_score += ai_points

    progress[current_category]["done"][idx] = True
    progress[current_category]["answered"] += 1
    progress[current_category]["index"] = idx + 1
    progress[current_category]["user_score"] += user_points
    progress[current_category]["ai_score"] += ai_points
    current_question_answered = True
    submit_button.config(state="disabled")
    show_button.config(state="disabled")
    answer_entry.config(state="disabled")
    if not option_buttons:
        render_option_buttons(disabled=True, mark_shown=True, show_idx=idx)
    else:
        # if the options already exist but weren't marked shown, keep them flagged
        progress[current_category]["shown"][idx] = True
    # show icons and fade in on the selected row labels
    _update_row_icons(user, ai_answer)
    # highlight options colors
    _highlight_options(user, ai_answer, correct)
    disable_option_buttons()
    if progress[current_category]["failed"] or progress[current_category]["index"] >= len(game_data[current_category]):
        next_button.config(state="disabled")
    else:
        next_button.config(state="normal")

    result_text += f" | KI: +{ai_points}"

    last_action = {
        "category": current_category,
        "idx": idx,
        "correct": correct_answer,
        "user_points": user_points,
        "ai_points": ai_points,
        "previous_failed": previous_failed,
        "previous_failed_index": previous_failed_index,
    }

    # make undo available until the user clicks elsewhere
    try:
        undo_clickable = True
    except Exception:
        pass

    result_label.config(text=result_text)
    update_undo_button()
    update_score()
    update_category_button(current_category)

# -----------------------------
# CATEGORY BUTTONS
# -----------------------------
tk.Label(left_frame, text="Categories", font=("Arial", 14)).pack(pady=10)
category_container = tk.Frame(left_frame)
category_container.pack(fill="both", expand=True)

for cat in game_data.keys():
    row = tk.Frame(category_container)
    row.pack(fill="x", pady=4, padx=5)

    header = tk.Frame(row)
    header.pack(fill="x")

    btn = tk.Button(header, text=cat,
                    command=lambda c=cat: load_category(c), font=("Arial", 12), anchor="w", justify="left")
    btn.default_bg = btn.cget("bg")
    btn.pack(side="left", fill="both", expand=True)

    score_lbl = tk.Label(header, text="0-0", font=("Arial", 12))
    score_lbl.pack(side="right", padx=(10, 0))

    q_frame = tk.Frame(row)
    q_frame.pack(fill="x", pady=(2, 0))

    q_buttons = []
    for q_idx in range(min(5, len(game_data[cat]))):
        q_btn = tk.Button(q_frame, text=str(q_idx + 1),
                          command=lambda c=cat, idx=q_idx: load_category_question(c, idx),
                          font=("Arial", 10), width=3)
        q_btn.default_bg = q_btn.cget("bg")
        q_btn.pack(side="left", padx=2)
        q_buttons.append(q_btn)

    category_buttons[cat] = {"button": btn, "score": score_lbl, "question_buttons": q_buttons}

update_all_category_buttons()

# -----------------------------
# START
# Volume sliders (styled) at bottom-right
try:
    style = ttk.Style()
    # try to use default theme; configure a simple trough color
    try:
        style.theme_use('default')
    except Exception:
        pass
    style.configure('Vol.Horizontal.TScale', troughcolor='#e6e6e6', background='#4caf50')
except Exception:
    style = None

bottom_container = tk.Frame(right_frame)
bottom_container.pack(side="bottom", fill="x", padx=10, pady=10)

action_frame = tk.Frame(bottom_container)
action_frame.pack(side="left", fill="x", expand=True)

submit_button = tk.Button(action_frame, text="Submit Answer",
                           command=lambda: submit("submit"), font=("Arial", 14), width=24)
submit_button.pack(pady=6, ipadx=4, ipady=10)

show_button = tk.Button(action_frame, text="Show Answers",
                        command=show_options, font=("Arial", 14), width=24)
show_button.pack(pady=6, ipadx=4, ipady=10)

next_button = tk.Button(action_frame, text="Nächste Frage",
                        command=next_question,
                        state="disabled", font=("Arial", 14), width=24)
next_button.pack(pady=6, ipadx=4, ipady=10)

vol_frame = tk.Frame(bottom_container)
vol_frame.pack(side="right", anchor="e")

tk.Label(vol_frame, text="Music Vol", font=("Arial", 9)).pack(anchor="e")
music_scale = ttk.Scale(vol_frame, from_=0, to=1, orient="horizontal", length=160, command=set_music_volume, style='Vol.Horizontal.TScale')
music_scale.set(music_volume)
music_scale.pack(pady=4)

tk.Label(vol_frame, text="Effects Vol", font=("Arial", 9)).pack(anchor="e")
effects_scale = ttk.Scale(vol_frame, from_=0, to=1, orient="horizontal", length=160, command=set_effects_volume, style='Vol.Horizontal.TScale')
effects_scale.set(effects_volume)
effects_scale.pack(pady=4)

# -----------------------------
def on_close():
    stop_background()
    try:
        pygame.mixer.music.stop()
        pygame.mixer.quit()
        pygame.quit()
    except Exception:
        pass
    root.destroy()

def _global_click(event):
    """Disable undo if the user clicks anywhere except the undo button.

    This makes the "Undo letzte Frage" button only active until the user
    interacts elsewhere.
    """
    global undo_clickable
    try:
        w = event.widget
        # Walk up the widget hierarchy. Only clicks on enabled Buttons
        # (tk.Button or ttk.Button) count as user actions that disable undo.
        while w is not None:
            try:
                if w is undo_button:
                    return
                if isinstance(w, (tk.Button, ttk.Button)):
                    try:
                        state = w.cget("state")
                    except Exception:
                        state = None
                    # only treat enabled buttons as actions
                    if state is None or state != "disabled":
                        if undo_clickable:
                            undo_clickable = False
                            try:
                                update_undo_button()
                            except Exception:
                                pass
                    return
            except Exception:
                pass
            w = getattr(w, 'master', None)
    except Exception:
        pass

# bind globally to detect clicks
try:
    root.bind_all("<Button-1>", _global_click, add=True)
except Exception:
    pass

root.protocol("WM_DELETE_WINDOW", on_close)

update_score()
root.mainloop()