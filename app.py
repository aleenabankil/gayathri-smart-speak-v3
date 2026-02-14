from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
from dotenv import load_dotenv
from gtts import gTTS
from difflib import SequenceMatcher
from groq import Groq
import uuid
import re
import json
from datetime import datetime
import random

# ================= SETUP =================
load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-in-production'

# Separate conversation contexts for each mode
conversation_contexts = {}  # Format: {user_id: {'conversation': '', 'roleplay': ''}}

# User database
users_db = {}

# Teacher database (now includes registered teachers)
teachers_db = {}

# Progressive XP requirements
def get_xp_for_level(level):
    """Calculate total XP required to reach a level"""
    if level <= 1:
        return 0
    xp = 0
    for l in range(1, level):
        if l == 1:
            xp += 25
        else:
            xp += 30
    return xp

def calculate_level(xp):
    """Calculate level based on current XP"""
    level = 1
    while xp >= get_xp_for_level(level + 1):
        level += 1
    return level

def get_xp_for_next_level(current_level):
    """Get XP required for next level"""
    if current_level == 1:
        return 25
    else:
        return 30

def get_difficulty_for_level(level):
    """Auto-adjust difficulty based on level"""
    if level <= 2:
        return "easy"
    elif level <= 4:
        return "easy"
    elif level <= 7:
        return "medium"
    elif level <= 10:
        return "medium"
    else:
        return "hard"

def save_user_progress(user_id, stars_earned, mode):
    """Save user progress and update XP"""
    if user_id in users_db:
        old_level = users_db[user_id]['level']
        users_db[user_id]['total_xp'] += stars_earned
        users_db[user_id]['total_stars'] += stars_earned
        new_level = calculate_level(users_db[user_id]['total_xp'])
        users_db[user_id]['level'] = new_level
        users_db[user_id]['last_active'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if mode not in users_db[user_id]['mode_stats']:
            users_db[user_id]['mode_stats'][mode] = {'stars': 0, 'sessions': 0}
        
        users_db[user_id]['mode_stats'][mode]['stars'] += stars_earned
        users_db[user_id]['mode_stats'][mode]['sessions'] += 1
        
        save_database()
        
        return {
            'leveled_up': new_level > old_level,
            'new_level': new_level,
            'old_level': old_level
        }
    return None

def save_database():
    """Save databases to JSON files"""
    try:
        with open('users_data.json', 'w') as f:
            json.dump(users_db, f, indent=2)
        with open('teachers_data.json', 'w') as f:
            json.dump(teachers_db, f, indent=2)
    except Exception as e:
        print(f"Error saving database: {e}")

def load_database():
    """Load databases from JSON files"""
    global users_db, teachers_db
    try:
        if os.path.exists('users_data.json'):
            with open('users_data.json', 'r') as f:
                users_db = json.load(f)
        if os.path.exists('teachers_data.json'):
            with open('teachers_data.json', 'r') as f:
                teachers_db = json.load(f)
    except Exception as e:
        print(f"Error loading database: {e}")
        users_db = {}
        teachers_db = {}

load_database()

def get_user_context(user_id, mode):
    """Get conversation context for specific user and mode"""
    if user_id not in conversation_contexts:
        conversation_contexts[user_id] = {'conversation': '', 'roleplay': ''}
    return conversation_contexts[user_id].get(mode, '')

def update_user_context(user_id, mode, context):
    """Update conversation context for specific user and mode"""
    if user_id not in conversation_contexts:
        conversation_contexts[user_id] = {'conversation': '', 'roleplay': ''}
    conversation_contexts[user_id][mode] = context[-1200:]  # Keep last 1200 chars

# ================= TTS =================
def speak_to_file(text, slow=False):
    os.makedirs("static/audio", exist_ok=True)
    filename = f"{uuid.uuid4()}.mp3"
    path = f"static/audio/{filename}"
    gTTS(text=text, lang="en", slow=slow).save(path)
    return "/" + path

# ================= AI FUNCTIONS WITH ISOLATED MEMORY =================

def english_coach(child_text, user_id):
    """Conversation mode with isolated memory per user"""
    context = get_user_context(user_id, 'conversation')
    
    prompt_variations = [
        "make the response natural and conversational",
        "use different words than previous responses",
        "be creative with your follow-up question",
        "vary your praise words",
        "ask about different topics each time"
    ]
    variation_hint = random.choice(prompt_variations)

    prompt = f"""
You are an English speaking coach for children aged 6 to 15.

STRICT RULES:
- Always correct the child's sentence
- If only one word, make a full sentence
- Very simple English
- Encourage the child with VARIED praise words
- Ask ONE follow-up question about DIFFERENT topics each time
- No grammar explanation
- {variation_hint}

Respond ONLY in this format:

CORRECT: <correct sentence>
PRAISE: <short encouragement - use different words>
QUESTION: <one simple question about a NEW topic>

Conversation so far:
{context}

Child says:
"{child_text}"
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        top_p=0.9
    )

    reply = response.choices[0].message.content.strip()
    new_context = context + f"\nChild: {child_text}\nAssistant: {reply}"
    update_user_context(user_id, 'conversation', new_context)
    
    return reply

def roleplay_coach(child_text, roleplay_type, user_id):
    """Roleplay mode with isolated memory per user"""
    context = get_user_context(user_id, 'roleplay')

    roles = {
        "teacher": """
You are a kind school teacher.
Help the student learn English.
Ask VARIED study-related questions about different subjects.
Be encouraging and patient.
""",
        "friend": """
You are a friendly classmate.
Talk casually and happily.
Ask about DIFFERENT daily activities, hobbies, interests.
Be cheerful and supportive.
""",
        "interviewer": """
You are a job interviewer.
Be polite and professional.
Ask DIFFERENT short interview questions each time.
Be encouraging but professional.
""",
        "viva": """
You are a viva examiner.
Ask DIFFERENT academic project questions.
Focus on understanding various aspects.
Be fair and encouraging.
"""
    }

    role_instruction = roles.get(roleplay_type, "You are a friendly English speaking partner.")
    variety_hints = [
        "Ask about something you haven't asked before",
        "Use different question words",
        "Focus on a different aspect",
        "Be creative and engaging"
    ]
    variety_hint = random.choice(variety_hints)

    prompt = f"""
{role_instruction}

You are doing roleplay with a student aged 6 to 15.

STRICT RULES:
- Always correct the student's sentence
- Very simple English
- Stay strictly in your role
- Encourage the student with VARIED praise
- Ask ONE role-based question
- No grammar explanation
- {variety_hint}

Respond ONLY in this format:

CORRECT: <correct sentence>
PRAISE: <short encouragement - vary your words>
QUESTION: <one NEW question relevant to your role>

Conversation so far:
{context}

Student says:
"{child_text}"
"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        top_p=0.9
    )

    reply = response.choices[0].message.content.strip()
    new_context = context + f"\nStudent: {child_text}\nAssistant: {reply}"
    update_user_context(user_id, 'roleplay', new_context)
    
    return reply

# ================= REPEAT & SPELL BEE FUNCTIONS =================
def generate_repeat_sentence(category="general", difficulty="easy", user_level=1):
    """Generate sentences with more variety"""
    
    if user_level <= 2:
        actual_difficulty = "easy"
    elif user_level <= 4:
        actual_difficulty = "easy" if difficulty == "easy" else "medium"
    elif user_level <= 7:
        actual_difficulty = difficulty if difficulty != "hard" else "medium"
    elif user_level <= 10:
        actual_difficulty = difficulty
    else:
        actual_difficulty = "hard" if difficulty == "hard" else difficulty
    
    word_limits = {
        "easy": "3 to 5 words",
        "medium": "6 to 9 words",
        "hard": "10 to 15 words"
    }
   
    category_details = {
        "general": {
            "description": "everyday activities, common objects, and simple actions",
            "easy": ["I love ice cream", "The sun is bright", "Mom reads books", "Birds sing songs", 
                    "We play games", "Rain feels cold", "Trees are tall", "Flowers smell nice"],
            "medium": ["I brush my teeth every morning", "The blue sky looks very beautiful",
                      "My friend helps me with homework", "We watch movies on weekends",
                      "The library has many books", "I practice piano after school"],
            "hard": ["My favorite hobby is drawing colorful pictures in my notebook",
                    "Every evening I help my mother prepare delicious dinner for the family",
                    "During summer vacation we visit interesting places and take lots of photos"]
        },
        "animals": {
            "description": "animals, pets, wildlife, and their behaviors",
            "easy": ["Dogs can bark loudly", "Cats like to sleep", "Birds fly very high", 
                    "Fish swim in water", "Horses run so fast", "Monkeys climb trees",
                    "Rabbits hop around", "Butterflies are pretty"],
            "medium": ["My rabbit eats fresh carrots daily", "The elephant has a very long trunk",
                      "Dolphins are intelligent marine mammals", "Penguins waddle on the ice",
                      "The lion is called king of the jungle", "Owls can see in the dark"],
            "hard": ["The playful dolphin jumps high above the sparkling blue ocean waves",
                    "Hummingbirds flap their tiny wings incredibly fast while drinking sweet nectar",
                    "Baby kangaroos stay safe inside their mother's warm pouch until they grow bigger"]
        },
        "food": {
            "description": "food items, meals, fruits, vegetables, and cooking",
            "easy": ["Pizza tastes really good", "I drink fresh milk", "Apples are so sweet",
                    "Cookies are yummy", "Soup is very hot", "Bread smells nice",
                    "Oranges are juicy", "Rice is white"],
            "medium": ["I eat healthy vegetables every single day", "My mom makes delicious chocolate cookies",
                      "Fresh fruit salad contains vitamins and minerals", "We bake birthday cakes together",
                      "Breakfast is the most important meal", "I prefer grilled chicken over fried"],
            "hard": ["For breakfast I enjoy eating scrambled eggs with crispy golden toast",
                    "My grandmother's homemade lasagna recipe has been passed down through generations",
                    "A balanced diet includes proteins vegetables fruits grains and dairy products daily"]
        },
        "sports": {
            "description": "sports, games, physical activities, and exercise",
            "easy": ["I can run fast", "Soccer is so fun", "We play basketball well",
                    "Swimming is cool", "I kick the ball", "Tennis needs a racket",
                    "Cycling is healthy", "Dancing makes me happy"],
            "medium": ["My sister swims in the pool today", "I practice tennis with my best friend",
                      "Basketball requires teamwork and coordination", "Running marathons needs lots of training",
                      "Gymnastics helps improve flexibility and balance", "Cricket is popular in many countries"],
            "hard": ["Every morning I ride my bicycle to the park with my friends",
                    "Professional athletes train rigorously for many hours every single day of the week",
                    "Playing team sports teaches important life skills like cooperation communication and leadership"]
        },
        "feelings": {
            "description": "emotions, feelings, moods, and personal expressions",
            "easy": ["I feel very happy", "She looks quite sad", "We are so excited",
                    "He seems angry", "They feel scared", "I am so proud",
                    "She is very calm", "We feel grateful"],
            "medium": ["My brother feels proud of his work", "I am really nervous about the test",
                      "Everyone felt disappointed when it rained", "Kindness makes people feel appreciated",
                      "I was surprised by the unexpected gift", "She remained confident during the competition"],
            "hard": ["When my friends visit me I always feel extremely happy and joyful",
                    "Understanding and managing our emotions effectively helps us maintain healthy relationships",
                    "Sometimes feeling sad or disappointed is completely normal and helps us grow stronger"]
        },
        "colors": {
            "description": "colors, shapes, sizes, and visual descriptions",
            "easy": ["The car is red", "I see yellow flowers", "Her dress looks blue",
                    "Grass is green", "Snow is white", "The night is dark",
                    "Carrots are orange", "Grapes are purple"],
            "medium": ["The rainbow has many beautiful bright colors", "My new backpack is dark purple color",
                      "Autumn leaves turn golden yellow and orange", "The sunset painted the sky pink",
                      "Different shades of blue represent various moods", "Artists mix colors to create new ones"],
            "hard": ["The gigantic orange pumpkin sits in our garden looking absolutely magnificent",
                    "Fashion designers carefully select complementary colors to create stunning visual combinations",
                    "Understanding color theory helps artists painters and designers create more appealing artwork"]
        },
        "family": {
            "description": "family members, relatives, friends, and relationships",
            "easy": ["Dad helps me learn", "I love my sister", "Grandma tells great stories",
                    "Mom cooks dinner", "My brother is funny", "Uncle visits often",
                    "Aunt is kind", "Cousins play together"],
            "medium": ["My cousin visits us every summer vacation", "Uncle Tom teaches me how to swim",
                      "Grandparents share wisdom from their experiences", "Family traditions bring everyone closer together",
                      "Siblings sometimes argue but always make up", "Extended family gatherings are always fun"],
            "hard": ["On weekends my whole family enjoys eating dinner together at the table",
                    "Family bonds grow stronger when we spend quality time communicating and supporting each other",
                    "Multi-generational households allow grandparents parents and children to learn from one another"]
        },
        "school": {
            "description": "school activities, learning, education, and classroom experiences",
            "easy": ["I like my teacher", "Math class is fun", "We learn new things",
                    "Books are helpful", "Friends are nice", "Lunch is tasty",
                    "Science is interesting", "Art is creative"],
            "medium": ["My favorite subject in school is science", "I always do my homework after school",
                      "Teachers help students understand difficult concepts", "Group projects teach collaboration skills",
                      "Libraries provide resources for research", "Physical education keeps students active"],
            "hard": ["During art class we create beautiful paintings using watercolors and special brushes",
                    "Effective study habits include regular practice active participation and asking questions when confused",
                    "Modern classrooms use technology like computers tablets and interactive whiteboards to enhance learning"]
        }
    }
   
    category_info = category_details.get(category, category_details["general"])
    category_context = category_info["description"]
    word_limit = word_limits.get(actual_difficulty, "3 to 5 words")
    examples = category_info.get(actual_difficulty, category_info.get("easy", []))
    
    if len(examples) > 3:
        examples = random.sample(examples, 3)
    
    if not examples or len(examples) < 3:
        examples = ["I like to play", "The sun is bright", "We have fun together"]
    
    variety_seed = datetime.now().microsecond % 100

    prompt = f"""You are an expert English teacher for children aged 6 to 15.

TASK: Create ONE UNIQUE, simple, natural sentence for speaking practice.

CATEGORY: {category_context}
DIFFICULTY: {actual_difficulty}
WORD COUNT: Must be {word_limit}
USER LEVEL: {user_level}

CRITICAL RULES FOR VARIETY:
1. DO NOT repeat common phrases
2. Use DIFFERENT sentence structures
3. Vary subjects and verbs
4. Be creative and unexpected
5. Return ONLY the sentence - no quotes, punctuation, or extra text
6. Make it natural and interesting
7. Use present, past, or future tense (vary this!)
8. Be creative and original!

VARIETY SEED: {variety_seed}

GOOD EXAMPLES for {category} ({actual_difficulty}):
- {examples[0]}
- {examples[1]}
- {examples[2]}

Now create ONE COMPLETELY NEW AND DIFFERENT sentence."""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.95,
        top_p=0.95,
        max_tokens=60
    )

    sentence = response.choices[0].message.content.strip()
    sentence = re.sub(r'^["\']+|["\']+$', '', sentence)
    sentence = re.sub(r'[.!?;:,]+$', '', sentence)
    sentence = sentence.strip()
    
    if sentence:
        sentence = sentence[0].upper() + sentence[1:]
   
    return sentence

def generate_spell_word(difficulty="easy", user_level=1):
    """Generate words with variety"""
    
    if user_level <= 2:
        actual_difficulty = "easy"
    elif user_level <= 7:
        actual_difficulty = difficulty if difficulty != "hard" else "medium"
    else:
        actual_difficulty = difficulty
    
    word_pools = {
        "easy": [
            "cat", "dog", "sun", "moon", "tree", "fish", "bird", "house", "book", "star",
            "ball", "cake", "milk", "rain", "snow", "wind", "fire", "door", "hand", "foot",
            "head", "nose", "eyes", "hair", "bike", "boat", "car", "bus", "lamp", "bell",
            "desk", "chair", "plant", "flower", "grass", "cloud", "smile", "happy", "jump", "sing"
        ],
        "medium": [
            "elephant", "butterfly", "rainbow", "mountain", "ocean", "garden", "kitchen", "bedroom",
            "library", "hospital", "balloon", "chocolate", "sandwich", "umbrella", "telephone",
            "computer", "bicycle", "monkey", "giraffe", "pencil", "notebook", "beautiful",
            "wonderful", "excellent", "surprise", "remember", "favorite", "together", "tomorrow",
            "yesterday", "adventure", "question", "answer", "different", "important", "birthday",
            "holiday", "vacation", "celebration", "gratitude"
        ],
        "hard": [
            "magnificent", "extraordinary", "intelligence", "temperature", "environment",
            "photography", "responsibility", "appreciate", "participate", "communicate",
            "imagination", "encyclopedia", "sophisticated", "achievement", "opportunity",
            "enthusiasm", "independent", "understand", "comfortable", "accomplish",
            "neighborhood", "refrigerator", "pronunciation", "explanation", "demonstration",
            "disappointed", "embarrassed", "fortunately", "unfortunately", "particularly",
            "absolutely", "actually", "basically", "completely", "definitely", "especially",
            "immediately", "necessary", "obviously", "seriously"
        ]
    }
    
    word_list = word_pools.get(actual_difficulty, word_pools["easy"])
    word = random.choice(word_list)
    
    return word.lower()

def get_word_sentence_usage(word):
    """Generate varied example sentences"""
    
    sentence_patterns = [
        f"Use the word in a sentence about daily life",
        f"Create a sentence showing what this word means",
        f"Make a simple example using this word",
        f"Show how children would use this word",
        f"Give a clear example with this word"
    ]
    
    pattern = random.choice(sentence_patterns)

    prompt = f"""Create ONE simple example sentence using the word "{word}".

{pattern}

RULES:
1. Sentence must be simple for children aged 6-15
2. Clearly show the word's meaning
3. Use simple vocabulary
4. Make it relatable to children
5. Be creative and varied
6. Return ONLY the sentence - no quotes
7. Use different sentence structures
8. Vary tenses

Now create a NEW, DIFFERENT sentence using "{word}"."""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        max_tokens=50
    )

    sentence = response.choices[0].message.content.strip()
    sentence = re.sub(r'^["\']+|["\']+$', '', sentence)
   
    return sentence

def get_word_meaning(word):
    prompt = f"""You are an English teacher explaining word meanings to children aged 6 to 15.

Word: "{word}"

FORMAT YOUR RESPONSE EXACTLY AS:
MEANING: <simple definition in 1-2 sentences>
EXAMPLE: <one simple example sentence using the word>
TYPE: <noun/verb/adjective/adverb/etc>
TIP: <one helpful tip about using this word>

RULES:
1. Use very simple language
2. Avoid complex terminology
3. Make examples relatable
4. Be encouraging
5. Focus on most common meaning
6. Keep explanations short"""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=200
    )

    return response.choices[0].message.content.strip()

def compare_words(student_text, correct_text):
    student_words = student_text.lower().split()
    correct_words = correct_text.lower().split()
    comparison = []
    
    for i, correct_word in enumerate(correct_words):
        if i < len(student_words):
            student_word = student_words[i]
            similarity = SequenceMatcher(None, student_word, correct_word).ratio()
            
            if similarity >= 0.8:
                comparison.append({"word": correct_word, "status": "correct"})
            else:
                comparison.append({"word": correct_word, "status": "incorrect", "spoken": student_word})
        else:
            comparison.append({"word": correct_word, "status": "missing"})
    
    return comparison

def compare_spelling(student_spelling, correct_word):
    student = student_spelling.lower().strip()
    correct = correct_word.lower().strip()
    comparison = []
    max_len = max(len(student), len(correct))
    
    for i in range(max_len):
        if i < len(correct):
            correct_letter = correct[i]
            if i < len(student):
                student_letter = student[i]
                if student_letter == correct_letter:
                    comparison.append({"letter": correct_letter, "status": "correct"})
                else:
                    comparison.append({"letter": correct_letter, "status": "incorrect", "typed": student_letter})
            else:
                comparison.append({"letter": correct_letter, "status": "missing"})
    
    return comparison

# ================= ROUTES =================
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/user-type")
def user_type():
    """Page to select user type (student or teacher)"""
    return render_template("user_type.html")

@app.route("/login", methods=["GET"])
def login_page():
    user_type = request.args.get("type", "student")
    return render_template("login.html", user_type=user_type)

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user_id = data.get("user_id")
    password = data.get("password")
    user_type = data.get("user_type", "student")
    
    if user_type == "teacher":
        # Teacher login
        if user_id in teachers_db:
            if teachers_db[user_id]['password'] == password:
                session['user_id'] = user_id
                session['role'] = 'teacher'
                return jsonify({"success": True, "redirect": "/teacher-dashboard"})
            else:
                return jsonify({"success": False, "message": "Incorrect password."})
        else:
            return jsonify({"success": False, "message": "Teacher username not found."})
    else:
        # Student login
        if user_id and password:
            if user_id in users_db:
                if users_db[user_id]['password'] == password:
                    session['user_id'] = user_id
                    session['role'] = 'student'
                    return jsonify({"success": True, "redirect": "/main"})
                else:
                    return jsonify({"success": False, "message": "Incorrect password."})
            else:
                return jsonify({"success": False, "message": "User ID not found. Please sign up first."})
        else:
            return jsonify({"success": False, "message": "Please enter both User ID and Password."})

@app.route("/signup", methods=["GET"])
def signup_page():
    user_type = request.args.get("type", "student")
    return render_template("signup.html", user_type=user_type)

@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    user_type = data.get("user_type", "student")
    
    if user_type == "teacher":
        # Teacher signup
        username = data.get("username")
        password = data.get("password")
        name = data.get("name")
        
        if username and password and name:
            if len(username) == 6 and len(password) == 6:
                # Check if username already exists
                if username in teachers_db:
                    return jsonify({"success": False, "message": "Username already exists. Please choose another."})
                else:
                    teachers_db[username] = {
                        "password": password,
                        "name": name,
                        "role": "teacher",
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    save_database()
                    session['user_id'] = username
                    session['role'] = 'teacher'
                    return jsonify({"success": True, "redirect": "/teacher-dashboard"})
            else:
                return jsonify({"success": False, "message": "Username and Password must be exactly 6 characters each."})
        else:
            return jsonify({"success": False, "message": "Please fill in all fields."})
    else:
        # Student signup
        user_id = data.get("user_id")
        password = data.get("password")
        name = data.get("name")
        student_class = data.get("class")
        division = data.get("division")
        
        if user_id and password and name and student_class and division:
            if len(user_id) == 3 and user_id.isdigit():
                if user_id in users_db:
                    return jsonify({"success": False, "message": "User ID already exists. Please login or choose a different ID."})
                else:
                    users_db[user_id] = {
                        "password": password,
                        "name": name,
                        "class": student_class,
                        "division": division,
                        "total_xp": 0,
                        "total_stars": 0,
                        "level": 1,
                        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "last_active": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "mode_stats": {}
                    }
                    save_database()
                    session['user_id'] = user_id
                    session['role'] = 'student'
                    return jsonify({"success": True, "redirect": "/main"})
            else:
                return jsonify({"success": False, "message": "User ID must be exactly 3 digits."})
        else:
            return jsonify({"success": False, "message": "Please fill in all fields."})

@app.route("/main")
def main():
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('home'))
    
    user_id = session['user_id']
    user_data = users_db.get(user_id, {})
    
    recommended_difficulty = get_difficulty_for_level(user_data.get('level', 1))
    
    current_level = user_data.get('level', 1)
    current_xp = user_data.get('total_xp', 0)
    xp_for_current_level = get_xp_for_level(current_level)
    xp_for_next_level = get_xp_for_level(current_level + 1)
    xp_in_current_level = current_xp - xp_for_current_level
    xp_needed_for_next = xp_for_next_level - xp_for_current_level
    
    return render_template("main.html", 
                         user_id=user_id, 
                         user_data=user_data,
                         recommended_difficulty=recommended_difficulty,
                         xp_in_current_level=xp_in_current_level,
                         xp_needed_for_next=xp_needed_for_next)

@app.route("/profile")
def profile():
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('home'))
    
    user_id = session['user_id']
    user_data = users_db.get(user_id, {})
    
    current_level = user_data.get('level', 1)
    current_xp = user_data.get('total_xp', 0)
    xp_for_current_level = get_xp_for_level(current_level)
    xp_for_next_level = get_xp_for_level(current_level + 1)
    xp_in_current_level = current_xp - xp_for_current_level
    xp_needed_for_next = xp_for_next_level - xp_for_current_level
    
    return render_template("profile.html",
                         user_id=user_id,
                         user_data=user_data,
                         xp_in_current_level=xp_in_current_level,
                         xp_needed_for_next=xp_needed_for_next)

@app.route("/teacher-dashboard")
def teacher_dashboard():
    if 'user_id' not in session or session.get('role') != 'teacher':
        return redirect(url_for('home'))
    
    students_by_class = {}
    total_students = 0
    total_stars_all = 0
    
    for user_id, user_data in users_db.items():
        class_key = f"Class {user_data['class']}{user_data['division']}"
        if class_key not in students_by_class:
            students_by_class[class_key] = []
        students_by_class[class_key].append({
            'user_id': user_id,
            'name': user_data['name'],
            'level': user_data['level'],
            'total_xp': user_data['total_xp'],
            'total_stars': user_data['total_stars'],
            'last_active': user_data['last_active'],
            'class': user_data['class'],
            'division': user_data['division']
        })
        total_students += 1
        total_stars_all += user_data['total_stars']
    
    for class_key in students_by_class:
        students_by_class[class_key].sort(key=lambda x: x['total_xp'], reverse=True)
    
    teacher_name = teachers_db[session['user_id']]['name']
    
    return render_template("teacher_dashboard.html",
                         students_by_class=students_by_class,
                         teacher_name=teacher_name,
                         total_students=total_students,
                         total_classes=len(students_by_class),
                         total_stars_all=total_stars_all)

@app.route("/logout")
def logout():
    user_id = session.get('user_id')
    role = session.get('role')
    
    # UPDATED: Save progress before logout
    if role == 'student' and user_id in users_db:
        users_db[user_id]['last_active'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_database()  # Explicitly save to JSON
    
    # Clear user's conversation context on logout
    if user_id and user_id in conversation_contexts:
        del conversation_contexts[user_id]
    
    session.pop('user_id', None)
    session.pop('role', None)
    return redirect(url_for('home'))

@app.route("/get_user_stats", methods=["GET"])
def get_user_stats():
    if 'user_id' not in session or session.get('role') != 'student':
        return jsonify({"success": False, "message": "Not logged in"})
    
    user_id = session['user_id']
    user_data = users_db.get(user_id, {})
    
    current_level = user_data.get('level', 1)
    current_xp = user_data.get('total_xp', 0)
    xp_for_current_level = get_xp_for_level(current_level)
    xp_for_next_level = get_xp_for_level(current_level + 1)
    xp_in_current_level = current_xp - xp_for_current_level
    xp_needed_for_next = xp_for_next_level - xp_for_current_level
    
    return jsonify({
        "success": True,
        "total_xp": user_data.get('total_xp', 0),
        "total_stars": user_data.get('total_stars', 0),
        "level": current_level,
        "xp_in_current_level": xp_in_current_level,
        "xp_needed_for_next": xp_needed_for_next,
        "recommended_difficulty": get_difficulty_for_level(current_level)
    })

# ---------- CONVERSATION & ROLEPLAY ----------
@app.route("/process", methods=["POST"])
def process():
    if 'user_id' not in session:
        return jsonify({"error": "Not logged in"}), 401
    
    data = request.json
    user_text = data["text"]
    roleplay = data.get("roleplay")
    user_id = session['user_id']

    if roleplay:
        ai_reply = roleplay_coach(user_text, roleplay, user_id)
    else:
        ai_reply = english_coach(user_text, user_id)

    correct = praise = question = ""
    for line in ai_reply.split("\n"):
        if line.startswith("CORRECT:"):
            correct = line.replace("CORRECT:", "").strip()
        elif line.startswith("PRAISE:"):
            praise = line.replace("PRAISE:", "").strip()
        elif line.startswith("QUESTION:"):
            question = line.replace("QUESTION:", "").strip()

    final_text = f"{correct}. {praise} {question}"
    audio = speak_to_file(final_text)

    return jsonify({
        "reply": final_text,
        "audio": audio
    })

# ---------- REPEAT AFTER ME ----------
@app.route("/repeat_sentence", methods=["POST"])
def repeat_sentence():
    data = request.json
    category = data.get("category", "general")
    difficulty = data.get("difficulty", "easy")
    
    user_level = 1
    if 'user_id' in session:
        user_data = users_db.get(session['user_id'], {})
        user_level = user_data.get('level', 1)
   
    sentence = generate_repeat_sentence(category, difficulty, user_level)
    audio_normal = speak_to_file(sentence, slow=False)
    audio_slow = speak_to_file(sentence, slow=True)

    return jsonify({
        "sentence": sentence,
        "audio": audio_normal,
        "audio_slow": audio_slow
    })

@app.route("/check_repeat", methods=["POST"])
def check_repeat():
    data = request.json
    student = data["student"]
    correct = data["correct"]
    stage_complete = data.get("stage_complete", False)

    score = SequenceMatcher(None, student.lower(), correct.lower()).ratio()
    word_comparison = compare_words(student, correct)

    if score >= 0.9:
        feedback = "Perfect! Amazing pronunciation!"
        stars = 3
    elif score >= 0.75:
        feedback = "Great job! Keep practicing!"
        stars = 2
    elif score >= 0.6:
        feedback = "Good try! Try speaking more clearly."
        stars = 1
    else:
        feedback = "Keep trying! Speak slowly and clearly."
        stars = 0

    # Only save progress if stage is complete (5 sentences done)
    level_info = None
    if stage_complete and 'user_id' in session:
        level_info = save_user_progress(session['user_id'], stars, 'repeat')

    return jsonify({
        "feedback": feedback,
        "score": round(score * 100),
        "stars": stars,
        "word_comparison": word_comparison,
        "level_info": level_info,
        "stars_saved": stage_complete
    })

# ---------- SPELL BEE ----------
@app.route("/spell_word", methods=["POST"])
def spell_word():
    data = request.json
    difficulty = data.get("difficulty", "easy")
    
    user_level = 1
    if 'user_id' in session:
        user_data = users_db.get(session['user_id'], {})
        user_level = user_data.get('level', 1)
   
    word = generate_spell_word(difficulty, user_level)
    usage = get_word_sentence_usage(word)
   
    audio_word = speak_to_file(word, slow=True)
    audio_sentence = speak_to_file(usage, slow=False)
   
    return jsonify({
        "word": word,
        "usage": usage,
        "audio_word": audio_word,
        "audio_sentence": audio_sentence
    })

@app.route("/check_spelling", methods=["POST"])
def check_spelling():
    data = request.json
    student_spelling = data["spelling"]
    correct_word = data["correct"]
    stage_complete = data.get("stage_complete", False)
   
    student = student_spelling.lower().strip()
    correct = correct_word.lower().strip()
   
    is_correct = (student == correct)
    letter_comparison = compare_spelling(student, correct)
   
    if is_correct:
        feedback = "🎉 Perfect! You spelled it correctly!"
        stars = 3
    else:
        similarity = SequenceMatcher(None, student, correct).ratio()
        if similarity >= 0.8:
            feedback = "Almost there! Check a few letters."
            stars = 2
        elif similarity >= 0.5:
            feedback = "Good try! Keep practicing!"
            stars = 1
        else:
            feedback = "Try again! Listen carefully to the word."
            stars = 0
    
    # Only save progress if stage is complete (5 words done)
    level_info = None
    if stage_complete and 'user_id' in session:
        level_info = save_user_progress(session['user_id'], stars, 'spellbee')
   
    return jsonify({
        "correct": is_correct,
        "feedback": feedback,
        "stars": stars,
        "letter_comparison": letter_comparison,
        "correct_spelling": correct,
        "level_info": level_info,
        "stars_saved": stage_complete
    })

# ---------- WORD MEANINGS ----------
@app.route("/get_meaning", methods=["POST"])
def get_meaning():
    data = request.json
    word = data["word"]
   
    meaning_response = get_word_meaning(word)
   
    meaning = usage = word_type = tip = ""
    for line in meaning_response.split("\n"):
        if line.startswith("MEANING:"):
            meaning = line.replace("MEANING:", "").strip()
        elif line.startswith("EXAMPLE:"):
            usage = line.replace("EXAMPLE:", "").strip()
        elif line.startswith("TYPE:"):
            word_type = line.replace("TYPE:", "").strip()
        elif line.startswith("TIP:"):
            tip = line.replace("TIP:", "").strip()
   
    audio_text = f"{word}. {meaning}. For example: {usage}. {tip}"
    audio = speak_to_file(audio_text, slow=False)
   
    return jsonify({
        "word": word,
        "meaning": meaning,
        "usage": usage,
        "type": word_type,
        "tip": tip,
        "audio": audio
    })

if __name__ == "__main__":
    app.run(debug=True)