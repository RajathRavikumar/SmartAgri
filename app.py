import google.generativeai as genai
import io
import base64
import re
import os
import requests
import bcrypt
import secrets
import logging
from flask import Flask, request, jsonify, render_template, redirect, url_for, session, flash, send_from_directory
from flask_pymongo import PyMongo
from PIL import Image
from googleapiclient.discovery import build  # YouTube API
from functools import wraps
from datetime import datetime, timedelta

# Initialize Flask app
app = Flask(__name__)

# SECRET KEY (for session management)
app.secret_key = secrets.token_hex(16)  # Generates a secure random key

# MongoDB Config
app.config["MONGO_URI"] = "mongodb://localhost:27017/smartagri"
mongo = PyMongo(app)

# Define MongoDB collections
users_collection = mongo.db.users
sessions_collection = mongo.db.sessions
ratings_collection = mongo.db.ratings  # Collection for star ratings
comments_collection = mongo.db.comments  # Collection for comments
crop_data_collection = mongo.db.crop_growth_analysis  # Collection for crop growth data
irrigation_plans_collection = mongo.db.irrigation_plans

# Google API Key (Used for Gemini & YouTube)
GOOGLE_API_KEY = "AIzaSyCtM8nDKzUuMMscdgGG-G2mpHl6jbDawmg"  # Replace with your actual API key

# OpenWeather API Key
OPENWEATHER_API_KEY = "058842609290a9c67ada17799607dfc9"  # Replace with your actual API key

# Configure Gemini AI
genai.configure(api_key=GOOGLE_API_KEY)

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Supported Languages with "none" added
LANGUAGES = {
    "none": "Auto",  # Added "none" as an option
    "en": "English",
    "kn": "Kannada",
    "hi": "Hindi",
    "sp": "Spanish",
    "te": "Telugu"
}

# Middleware to check active session before each request
@app.before_request
def check_session():
    if "user" in session:
        email = session["user"]
        user_session = mongo.db.sessions.find_one({"email": email})

        if not user_session:
            session.clear()
            flash("Your session has expired. Please log in again.", "error")
            return redirect(url_for("login"))

        # Check if session is expired
        expiry_time = user_session.get("expiry")
        if expiry_time and datetime.utcnow() > expiry_time:
            mongo.db.sessions.delete_many({"email": email})  # Remove expired session
            session.clear()
            flash("Your session has expired. Please log in again.", "error")
            return redirect(url_for("login"))

# Middleware to require login
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# Function to clean AI response text
def clean_text(text):
    text = re.sub(r"\*\*|\*", "", text)  # Remove **bold** and *italic* symbols
    text = text.replace("\n", "<br>")  # Convert new lines to HTML breaks
    return text

# Function to fetch YouTube video link for plant disease treatment
def get_youtube_video(query):
    try:
        youtube = build("youtube", "v3", developerKey=GOOGLE_API_KEY)
        search_response = youtube.search().list(
            q=query,
            part="snippet",
            maxResults=1,
            type="video"
        ).execute()

        if search_response.get("items", []):
            video_id = search_response["items"][0]["id"]["videoId"]
            return f"https://www.youtube.com/watch?v={video_id}"
        return "No relevant video found."
    except Exception as e:
        return f"Error fetching video: {str(e)}"

# Function to analyze plant disease (Image)
def analyze_disease_image(image_data, language="en"):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        encoded_image = base64.b64encode(image_data).decode("utf-8")

        response = model.generate_content([
            {"role": "user", "parts": [{"inline_data": {"mime_type": "image/jpeg", "data": encoded_image}}]},
            {"role": "user", "parts": [{"text": f"Identify the plant disease and provide its name, causes, and treatment. Respond in {LANGUAGES[language]}."}]}
        ])

        raw_text = response.text if hasattr(response, "text") else "No response from AI."
        cleaned_text = clean_text(raw_text)
        disease_name = cleaned_text.split("<br>")[0]
        youtube_video = get_youtube_video(disease_name + " disease treatment")

        return cleaned_text + f"<br><br>📺 Watch this video: <a href='{youtube_video}' target='_blank'>{youtube_video}</a>"
    except Exception as e:
        return f"Error processing image: {str(e)}"

# Function to analyze plant disease (Text Description)
def analyze_disease_description(description, language="en"):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Step 1: Detect the language of the description
        detection_prompt = f"Detect the language of this text: '{description}'. Return only the language code (e.g., 'en', 'kn', 'hi', 'sp', 'te')."
        detection_response = model.generate_content([{"role": "user", "parts": [{"text": detection_prompt}]}])
        detected_lang = detection_response.text.strip() if hasattr(detection_response, "text") else "en"
        logger.debug(f"Detected language of description: {detected_lang}")

        # Step 2: Determine the response language
        if language == "au":  # If "Auto" is selected
            response_lang = detected_lang if detected_lang in LANGUAGES else "en"
            logger.debug(f"Language set to 'Auto'; responding in detected language: {response_lang}")
        else:
            response_lang = language if language in LANGUAGES else "en"
            logger.debug(f"User-selected language: {response_lang}")
        
        # Step 3: Generate response in the determined language
        prompt = (
            f"Based on this description: '{description}', identify the plant disease and provide its name, causes, and treatment. "
            f"Respond only in {LANGUAGES[response_lang]}, do not include any other language."
        )
        response = model.generate_content([{"role": "user", "parts": [{"text": prompt}]}])

        raw_text = response.text if hasattr(response, "text") else f"No response from AI in {LANGUAGES[response_lang]}."
        cleaned_text = clean_text(raw_text)
        disease_name = cleaned_text.split("<br>")[0] if "<br>" in cleaned_text else cleaned_text
        youtube_video = get_youtube_video(disease_name + " disease treatment")

        return cleaned_text + f"<br><br>📺 Watch this video: <a href='{youtube_video}' target='_blank'>{youtube_video}</a>"
    except Exception as e:
        return f"Error processing description: {str(e)}"

# Updated get_weather function using forecast endpoint
def get_weather(lat, lon):
    logger.debug(f"Fetching weather for lat: {lat}, lon: {lon}")
    try:
        url = f"https://api.openweathermap.org/data/2.5/forecast?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
        logger.debug(f"Requesting URL: {url}")
        response = requests.get(url)
        data = response.json()

        logger.debug(f"API Response Status: {response.status_code}")
        logger.debug(f"API Response Data: {data}")

        if response.status_code == 200:
            location = data["city"]["name"]
            forecast = []
            daily_data = {}
            for entry in data["list"]:
                date = datetime.fromtimestamp(entry["dt"]).strftime("%Y-%m-%d")
                if date not in daily_data and len(daily_data) < 7:  # Limit to 7 days (5 in free tier)
                    daily_data[date] = {
                        "date": date,
                        "temperature": entry["main"]["temp"],
                        "humidity": entry["main"]["humidity"],
                        "wind_speed": entry["wind"]["speed"],
                        "description": entry["weather"][0]["description"],
                        "icon": f"https://openweathermap.org/img/wn/{entry['weather'][0]['icon']}@2x.png"
                    }
            forecast = list(daily_data.values())
            logger.debug(f"Forecast Data: {forecast}")
            return {"location": location, "forecast": forecast}
        else:
            error_message = data.get("message", "Unknown error")
            logger.error(f"API Error: {error_message}")
            return {"error": f"Unable to fetch weather details: {error_message}"}
    except Exception as e:
        logger.error(f"Exception occurred: {str(e)}")
        return {"error": f"Error fetching weather: {str(e)}"}

# Routes
@app.route("/")
def index():
    if "user" not in session:
        return redirect(url_for("login"))

    recent_comments = list(comments_collection.find().sort("timestamp", -1).limit(3))
    feedback_list = []
    for comment in recent_comments:
        email = comment["email"]
        user_rating = ratings_collection.find_one({"email": email}, sort=[("timestamp", -1)])
        feedback_list.append({
            "email": email,
            "comment": comment["comment"],
            "rating": user_rating["rating"] if user_rating else None,
            "timestamp": comment["timestamp"]
        })

    return render_template("index.html", feedback_list=feedback_list)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")

        existing_user = mongo.db.users.find_one({"email": email})
        if existing_user:
            flash("Email already registered. Please log in.", "warning")
            return redirect(url_for("login"))

        hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        mongo.db.users.insert_one({"name": name, "email": email, "password": hashed_password})
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = mongo.db.users.find_one({"email": email})
        if not user or not bcrypt.checkpw(password.encode("utf-8"), user["password"]):
            flash("Invalid email or password. Try again!", "error")
            return redirect(url_for("login"))
        
        app.permanent_session_lifetime = timedelta(days=1)
        session_token = secrets.token_hex(32)
        expiry_time = datetime.utcnow() + timedelta(days=1)

        mongo.db.sessions.update_one(
            {"email": email},
            {"$set": {"session_token": session_token, "expiry": expiry_time}},
            upsert=True
        )

        session["user"] = email
        session.permanent = True
        flash("Login successful!", "success")
        logger.debug("Redirecting to index...")
        return redirect(url_for("index"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    if "user" in session:
        email = session["user"]
        mongo.db.sessions.delete_many({"email": email})
        session.clear()
        flash("You have been logged out.", "info")
    return redirect(url_for("login"))

@app.route("/submit_rating", methods=["POST"])
@login_required
def submit_rating():
    data = request.get_json()
    rating = data.get("rating")

    if not rating or not isinstance(rating, int) or rating < 1 or rating > 5:
        return jsonify({"success": False, "message": "Invalid rating"}), 400

    rating_entry = {"email": session["user"], "rating": rating, "timestamp": datetime.utcnow()}
    ratings_collection.insert_one(rating_entry)
    return jsonify({"success": True, "message": "Rating submitted successfully"})

@app.route("/submit_comment", methods=["POST"])
@login_required
def submit_comment():
    data = request.get_json()
    comment = data.get("comment")

    if not comment or len(comment) > 500:
        return jsonify({"success": False, "message": "Invalid comment"}), 400

    comment_entry = {"email": session["user"], "comment": comment, "timestamp": datetime.utcnow()}
    comments_collection.insert_one(comment_entry)
    return jsonify({"success": True, "message": "Comment submitted successfully"})

@app.route("/chatbot", methods=["POST"])
@login_required
def agriculture_chatbot():
    logger.debug("Received request to /chatbot")
    try:
        data = request.json
        logger.debug(f"Request data: {data}")
        user_query = data.get("query")
        selected_language = data.get("language", "none")

        if not user_query:
            return jsonify({"error": "Please enter a question"}), 400

        model = genai.GenerativeModel("gemini-1.5-flash")
        detection_prompt = f"Detect the language of this text: '{user_query}'. Return only the language code (e.g., 'en', 'kn', 'hi', 'sp', 'te')."
        detection_response = model.generate_content([{"role": "user", "parts": [{"text": detection_prompt}]}])
        detected_lang = detection_response.text.strip() if hasattr(detection_response, "text") else "en"
        logger.debug(f"Detected language: {detected_lang}")

        if selected_language == "none":
            response_lang = detected_lang if detected_lang in LANGUAGES else "en"
            logger.debug(f"Selected language is 'none'; using detected language: {response_lang}")
        else:
            response_lang = selected_language if selected_language in LANGUAGES else "en"
            logger.debug(f"Selected language provided: {response_lang}")

        chat_prompt = (
            f"Agriculture expert chatbot. Answer this question: '{user_query}'. "
            f"Respond only in {LANGUAGES[response_lang]}, do not include any other language."
        )
        response = model.generate_content([{"role": "user", "parts": [{"text": chat_prompt}]}])

        raw_text = response.text if hasattr(response, "text") else f"No response from AI in {LANGUAGES[response_lang]}."
        cleaned_text = clean_text(raw_text)
        logger.debug(f"Response: {cleaned_text}")
        
        return jsonify({
            "response": cleaned_text,
            "detected_language": detected_lang,
            "response_language": response_lang,
            "reset_language_to": "none"
        })
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return jsonify({"error": f"Error processing request: {str(e)}"}), 500

@app.route("/disease_detection")
@login_required
def disease_detection():
    return render_template("disease_detection.html", languages=LANGUAGES)

@app.route("/upload", methods=["POST"])
@login_required
def upload_image_or_description():
    language = request.form.get("language", "en")

    if "image" in request.files and request.files["image"].filename != "":
        image = request.files["image"]
        img = Image.open(image)
        img_bytes = io.BytesIO()
        if img.mode == "RGBA":
            img = img.convert("RGB")
        img.save(img_bytes, format="JPEG")
        img_data = img_bytes.getvalue()
        result = analyze_disease_image(img_data, language)
        return jsonify({"disease_info": result})

    elif "description" in request.form and request.form["description"].strip() != "":
        description = request.form["description"]
        result = analyze_disease_description(description, language)
        return jsonify({"disease_info": result})

    return jsonify({"error": "Please provide an image or a description"}), 400

@app.route("/weather_forecast")
@login_required
def weather_page():
    return render_template("weather.html")

@app.route("/agrichat")
@login_required
def agri_chat():
    return render_template("agri_chat.html", languages=LANGUAGES)

@app.route("/weather", methods=["POST"])
@login_required
def weather():
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    lat = data.get("latitude")
    lon = data.get("longitude")

    if not lat or not lon:
        return jsonify({"error": "Latitude and Longitude are required"}), 400

    weather_data = get_weather(lat, lon)
    return jsonify(weather_data)

@app.route("/cropgrowthanalysis")
@login_required
def crop_growth_analysis():
    return render_template("cropgrowthanalysis.html")

@app.route("/analyze_crop_growth", methods=["POST"])
@login_required
def analyze_crop_growth():
    logger.debug("Received request to /analyze_crop_growth")
    try:
        data = request.json
        logger.debug(f"Request data: {data}")
        if not data:
            return jsonify({"error": "No data provided"}), 400

        required_fields = ["crop_type", "location"]
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        crop_type = data["crop_type"]
        location = data["location"]
        planting_date = data.get("planting_date", "Not provided")
        soil_quality = data.get("soil_quality", "Not provided")

        planting_date_str = "Not provided"
        if planting_date != "Not provided":
            try:
                planting_date = planting_date.replace("/", "-")
                planting_date_obj = datetime.strptime(planting_date, "%d-%m-%Y")
                planting_date_str = planting_date_obj.strftime("%Y-%m-%d")
            except ValueError:
                return jsonify({"error": "Invalid planting date format. Use DD-MM-YYYY or DD/MM/YYYY."}), 400

        weather_url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={OPENWEATHER_API_KEY}&units=metric"
        weather_response = requests.get(weather_url).json()

        if "main" not in weather_response:
            return jsonify({"error": "Invalid location"}), 400

        current_temperature = weather_response["main"]["temp"]
        current_humidity = weather_response["main"]["humidity"]
        current_weather_conditions = weather_response["weather"][0]["description"]

        prompt = (
            f"As an agriculture expert, evaluate this crop’s planting conditions:\n"
            f"- Crop Type: {crop_type}\n"
            f"- Location: {location}\n"
            f"- Planting Date: {planting_date_str}\n"
            f"- Soil Quality: {soil_quality}\n"
            f"- Current Date: 2025-03-25 (reference only, ignore for status)\n"
            f"- Current Temperature: {current_temperature}C (reference only)\n"
            f"- Current Humidity: {current_humidity}% (reference only)\n"
            f"- Current Weather: {current_weather_conditions} (reference only)\n"
            f"For {location} (Bangalore, India):\n"
            f"- Typical October weather: 25-28C, moderate rain\n"
            f"- Typical November weather: 20-25C, dry\n"
            f"- Typical December weather: 18-23C, dry\n"
            f"- Wheat planting season: October to early December\n"
            f"Base growth status only on typical weather and soil for {planting_date_str}.\n"
            f"Return exactly three lines in this format:\n"
            f"Growth Status: [Optimal, Poor, or Needs Attention]\n"
            f"Reason: [one sentence, max 10 words]\n"
            f"Best Planting Period: [e.g., October to November]\n"
            f"Default to 'Needs Attention' if unsure.\n"
            f"Use only letters, numbers, spaces, and hyphens."
        )

        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content([{"role": "user", "parts": [{"text": prompt}]}])
        
        raw_text = response.text if hasattr(response, "text") else f"Growth Status: Needs Attention\nReason: No AI response\nBest Planting Period: October to November"
        logger.debug(f"Gemini Raw Response: {raw_text}")

        lines = raw_text.split("\n")
        growth_status = "Needs Attention"
        growth_reason = "No reason provided"
        best_planting_period = "October to November"
        
        for line in lines:
            line = line.strip()
            if line.startswith("Growth Status:"):
                growth_status = line.replace("Growth Status:", "").strip()
            elif line.startswith("Reason:"):
                growth_reason = line.replace("Reason:", "").strip()
            elif line.startswith("Best Planting Period:"):
                best_planting_period = line.replace("Best Planting Period:", "").strip()

        valid_statuses = ["Optimal", "Poor", "Needs Attention"]
        if growth_status not in valid_statuses:
            growth_status = "Needs Attention"
            growth_reason = "AI returned invalid status"

        if not best_planting_period or len(best_planting_period.split()) < 3:
            best_planting_period = "October to November"
            growth_reason = "Invalid period format adjusted"

        growth_status = re.sub(r"[^a-zA-Z0-9\s\-]", "", growth_status)
        growth_reason = re.sub(r"[^a-zA-Z0-9\s\-]", "", growth_reason)
        best_planting_period = re.sub(r"[^a-zA-Z0-9\s\-]", "", best_planting_period)

        logger.debug(f"Parsed - Growth Status: {growth_status}, Reason: {growth_reason}, Best Planting Period: {best_planting_period}")

        crop_record = {
            "email": session["user"],
            "crop_type": crop_type,
            "location": location,
            "planting_date": planting_date_str,
            "soil_quality": soil_quality,
            "growth_stage": data.get("growth_stage", ""),
            "soil_nutrients": data.get("soil_nutrients", ""),
            "weather_conditions": current_weather_conditions,
            "temperature": current_temperature,
            "humidity": current_humidity,
            "growth_status": growth_status,
            "growth_reason": growth_reason,
            "best_planting_period": best_planting_period,
            "timestamp": datetime.utcnow()
        }
        crop_data_collection.insert_one(crop_record)

        return jsonify({"message": "Crop growth data saved successfully!", "data": crop_record})
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return jsonify({"error": f"Error processing request: {str(e)}"}), 500

@app.route("/irrigation_plan", methods=["GET", "POST"])
@login_required
def irrigation_plan():
    logger.debug("Received request to /irrigation_plan")
    if request.method == "GET":
        return render_template("irrigation_plan.html")

    try:
        data = request.json
        logger.debug(f"Request data: {data}")
        if not data:
            return jsonify({"error": "No data provided"}), 400

        required_fields = ["crop_type", "location"]
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({"error": f"Missing required field: {field}"}), 400

        crop_type = data["crop_type"]
        location = data["location"]
        planting_date = data.get("planting_date", "Not provided")
        growth_stage = data.get("growth_stage", "Not provided")

        planting_date_str = "Not provided"
        if planting_date != "Not provided":
            try:
                planting_date = planting_date.replace("/", "-")
                planting_date_obj = datetime.strptime(planting_date, "%d-%m-%Y")
                planting_date_str = planting_date_obj.strftime("%Y-%m-%d")
            except ValueError:
                return jsonify({"error": "Invalid planting date format. Use DD-MM-YYYY or DD/MM/YYYY."}), 400

        weather_url = f"http://api.openweathermap.org/data/2.5/weather?q={location}&appid={OPENWEATHER_API_KEY}&units=metric"
        weather_response = requests.get(weather_url).json()

        if "main" not in weather_response:
            return jsonify({"error": "Invalid location"}), 400

        temperature = weather_response["main"]["temp"]
        humidity = weather_response["main"]["humidity"]
        weather_conditions = weather_response["weather"][0]["description"]

        prompt = (
            f"As an irrigation expert, create a plan for this crop:\n"
            f"- Crop Type: {crop_type}\n"
            f"- Location: {location}\n"
            f"- Planting Date: {planting_date_str}\n"
            f"- Growth Stage: {growth_stage}\n"
            f"- Current Temperature: {temperature}C\n"
            f"- Current Humidity: {humidity}%\n"
            f"- Current Weather: {weather_conditions}\n"
            f"For {location} (Bangalore, India):\n"
            f"- Typical October: 25-28C, moderate rain\n"
            f"- Typical November: 20-25C, dry\n"
            f"- Typical December: 18-23C, dry\n"
            f"Return exactly three lines in this format:\n"
            f"Irrigation Frequency: [e.g., daily, weekly]\n"
            f"Water Amount: [e.g., X liters per hectare]\n"
            f"Reason: [one sentence, max 10 words]\n"
            f"Base plan on current weather and typical seasonal conditions.\n"
            f"Use only letters, numbers, spaces, and hyphens."
        )

        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content([{"role": "user", "parts": [{"text": prompt}]}])
        
        raw_text = response.text if hasattr(response, "text") else "Irrigation Frequency: weekly\nWater Amount: 5000 liters per hectare\nReason: Default irrigation plan"
        logger.debug(f"Gemini Raw Response: {raw_text}")

        lines = raw_text.split("\n")
        irrigation_frequency = "weekly"
        water_amount = "5000 liters per hectare"
        reason = "Default irrigation plan"
        
        for line in lines:
            line = line.strip()
            if line.startswith("Irrigation Frequency:"):
                irrigation_frequency = line.replace("Irrigation Frequency:", "").strip()
            elif line.startswith("Water Amount:"):
                water_amount = line.replace("Water Amount:", "").strip()
            elif line.startswith("Reason:"):
                reason = line.replace("Reason:", "").strip()

        irrigation_frequency = re.sub(r"[^a-zA-Z0-9\s\-]", "", irrigation_frequency)
        water_amount = re.sub(r"[^a-zA-Z0-9\s\-]", "", water_amount)
        reason = re.sub(r"[^a-zA-Z0-9\s\-]", "", reason)

        irrigation_record = {
            "email": session["user"],
            "crop_type": crop_type,
            "location": location,
            "planting_date": planting_date_str,
            "growth_stage": growth_stage,
            "temperature": temperature,
            "humidity": humidity,
            "weather_conditions": weather_conditions,
            "irrigation_frequency": irrigation_frequency,
            "water_amount": water_amount,
            "reason": reason,
            "timestamp": datetime.utcnow()
        }
        irrigation_plans_collection.insert_one(irrigation_record)

        return jsonify({"message": "Irrigation plan saved successfully!", "data": irrigation_record})
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        return jsonify({"error": f"Error processing request: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True)