import logging
import socket
import os
from dotenv import load_dotenv
import requests
import tkinter as tk
from tkinter import ttk
import firebase_admin
from firebase_admin import credentials, db
import threading
from PIL import Image, ImageTk
import cv2
import time
import pygame

# Load environment variables
load_dotenv()

# Briq API settings
SMS_API_KEY = os.getenv("BRIQ_API_KEY")
SMS_SENDER_ID = os.getenv("BRIQ_SENDER_ID", "BRIQ")  # Default to "BRIQ" if not set

# Configure logging
log_dir = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'queue_system.log')

logging.basicConfig(
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()  # This will also print logs to console
    ]
)

# Initialize Firebase
cred = credentials.Certificate("C:/Users/Administrator/Desktop/2021-04-01961/QUEUING SYSTEM PI-CODE/app/QueingSystem/code/picode/ServiceKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://beqs-651fc-default-rtdb.firebaseio.com/'
})

# Initialize global variables
queue = []  # Global queue to manage tokens
last_event_time = {}
DEBOUNCE_DELAY = 0.5  # 500 milliseconds

def handle_message(data):
    message = data.decode().strip()
    logging.info(f"Received raw message: {message}")
    
    # Split message into parts if it contains commas
    if "," in message:
        parts = message.split(",")
        
        # Handle TOKENIZER messages (with prefix)
        if parts[0] == "TOKENIZER" and len(parts) == 4:
            phone = parts[1].strip()
            token_str = parts[2].strip()
            token_type = parts[3].strip()

            # Validate the token is a number
            if token_str.isdigit():
                token = int(token_str)
                print(f"Received token: Phone={phone}, Token={token}, Type={token_type}")
                logging.info(f"Received token: Phone={phone}, Token={token}, Type={token_type}")

                # Add token to the queue with priority
                queue.append({"phone": phone, "token": token, "type": token_type})
                queue.sort(key=lambda x: 0 if x["type"].lower() == "priority" else 1)

                # Insert token into Firebase
                insert_token(token)

                # Send SMS to confirm token receipt
                send_sms(phone, f"Your token {token} has been received. Please wait for your turn.")

                # Check if token is three positions away from being served
                for i, q in enumerate(queue):
                    if q["token"] == token and i <= 2:
                        send_sms(phone, f"ALERT: Token {token} is {i+1} positions away!")
                        break
            else:
                print(f"Invalid token format: {token_str}")
                logging.warning(f"Invalid token format: {token_str}")
        
        # Handle direct token messages (without prefix) - phone,token,type
        elif len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            phone = parts[0].strip()
            token_str = parts[1].strip()
            token_type = parts[2].strip()

            # Validate the token is a number
            if token_str.isdigit():
                token = int(token_str)
                print(f"Received direct token: Phone={phone}, Token={token}, Type={token_type}")
                logging.info(f"Received direct token: Phone={phone}, Token={token}, Type={token_type}")

                # Add token to the queue with priority
                queue.append({"phone": phone, "token": token, "type": token_type})
                queue.sort(key=lambda x: 0 if x["type"].lower() == "priority" else 1)

                # Insert token into Firebase
                insert_token(token)

                # Send SMS to confirm token receipt
                send_sms(phone, f"Your token {token} has been received. Please wait for your turn.")

                # Check if token is three positions away from being served
                for i, q in enumerate(queue):
                    if q["token"] == token and i <= 2:
                        send_sms(phone, f"ALERT: Token {token} is {i+1} positions away!")
                        break
            else:
                print(f"Invalid token format: {token_str}")
                logging.warning(f"Invalid token format: {token_str}")
        
        # Handle TELLER messages
        elif parts[0] == "TELLER" and len(parts) == 2:
            action = parts[1].strip()
            if action == "D" or action == "1":
                # Handle teller's D key press or '1' key press
                counter_index = 0  # counter1 is at index 0
                current_token = token_number_labels[counter_index].cget("text")
                
                # If there's no token yet, start from 1, otherwise increment
                if not current_token:
                    next_token = 1
                else:
                    next_token = int(current_token) + 1
                    
                    # Validate maximum token number (e.g., 999)
                    if next_token > 999:
                        logging.warning(f"Token number {next_token} exceeds maximum (999)")
                        return
                
                # Update the counter with the new token
                update_counter('counter1', next_token)
                
                # Send SMS to the phone number associated with the token being served
                for q in queue:
                    if q["token"] == next_token:
                        phone = q["phone"]
                        send_sms(phone, f"Now is your time to be served. Please proceed to the counter.")
                        logging.info(f"Sent 'now is your time' SMS to {phone} for token {next_token}")
                        break
                
                # Log the update
                logging.info(f"Counter 1 token incremented to {next_token} from TELLER")
            elif action == "*":
                # Clear counter1
                reset_counter('counter1')
                logging.info("Counter 1 cleared from TELLER")
            elif action == "#":
                # Clear all counters
                for i in range(1, 5):  # Clear counters 1-4
                    counter_id = f"counter{i}"
                    reset_counter(counter_id)
                logging.info("All counters cleared from TELLER")
                
                # Also reset the database if TELLER,# is received
                reset_database()
                print("TELLER,# command received. Database cleared.")
                logging.info("TELLER,# command received. Database cleared.")
            else:
                logging.warning(f"Unknown TELLER action: {action}")
        else:
            print(f"Invalid message format: {message}")
            logging.warning(f"Invalid message format: {message}")
    elif message == "#":
        reset_database()
        print("Reset command '#' received. Database cleared.")
        logging.info("Reset command '#' received. Database cleared.")
    else:
        print(f"Incomplete or unrecognized data received: {message}")
        logging.info(f"Incomplete or unrecognized data received: {message}")

# UDP Listener Configuration
UDP_IP = "0.0.0.0"  # Listen on all interfaces
UDP_PORT = 12345  # Changed to match ESP32's port
BUFFER_SIZE = 1024

def udp_listener():
    """Start UDP listener in a separate thread"""
    print("Starting UDP listener...")
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Allow socket reuse
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((UDP_IP, UDP_PORT))
            print(f"✅ UDP listener started successfully on {UDP_IP}:{UDP_PORT}")
            logging.info(f"UDP listener started on {UDP_IP}:{UDP_PORT}")
            
            while True:
                try:
                    data, addr = sock.recvfrom(BUFFER_SIZE)
                    try:
                        message = data.decode().strip()
                        print(f"📨 Received UDP message: {message}")
                        logging.info(f"Received raw message: {message}")
                        
                        # Process the message using the handle_message function
                        handle_message(data)
                            
                    except UnicodeDecodeError:
                        logging.error("Failed to decode message")
                    except Exception as e:
                        logging.error(f"Error processing message: {e}")
                        
                except Exception as e:
                    logging.error(f"Error receiving UDP message: {e}")
                    continue

        except OSError as e:
            if e.errno == 10048:  # Address already in use
                print(f"⚠️ Port {UDP_PORT} is already in use. Retrying in 5 seconds...")
                logging.error(f"Port {UDP_PORT} is already in use. Retrying in 5 seconds...")
                time.sleep(5)  # Wait before retrying
                continue
            else:
                print(f"❌ UDP socket error: {e}")
                logging.error(f"UDP socket error: {e}")
                time.sleep(5)  # Wait before retrying
        except Exception as e:
            print(f"❌ UDP listener error: {e}")
            logging.error(f"UDP listener error: {e}")
            time.sleep(5)  # Wait before retrying
        finally:
            try:
                sock.close()
            except:
                pass

# Start UDP listener in a separate thread
print("🚀 Starting UDP listener thread...")
udp_thread = threading.Thread(target=udp_listener, daemon=True)
udp_thread.start()
print("✅ UDP listener thread started successfully!")

# Function to clear a specific counter when # is pressed
def clear_counter_input(input_string):
    # Check if the input is just '#'
    if input_string == "#":
        # Clear all counters
        for i in range(1, 5):  # Assuming 4 counters
            counter_id = f"counter{i}"
            reset_counter(counter_id)
            # Update the UI label for this counter
            counter_index = i - 1  # Convert to 0-based index
            token_number_labels[counter_index].config(text="")
            print(f"Counter {counter_id} cleared via input '{input_string}'")
            logging.info(f"Counter {counter_id} cleared via input '{input_string}'")
    else:
        print(f"Invalid input format: {input_string}")
        logging.warning(f"Invalid input format: {input_string}")

def send_sms(phone_number, message, max_retries=3):
    try:
        # Ensure phone number is in international format (+255 for Tanzania)
        if not phone_number.startswith("+"):
            phone_number = f"+255{phone_number[-9:]}"
        
        url = "https://karibu.briq.tz/v1/message/send-instant"
        headers = {
            "X-API-Key": SMS_API_KEY,  # Using from config file
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        payload = {
            "content": message,
            "recipients": [phone_number],
            "sender_id": SMS_SENDER_ID  # Using from config file
        }

        for attempt in range(max_retries):
            try:
                response = requests.post(url, json=payload, headers=headers)
                response.raise_for_status()
                result = response.json()
                print(f"SMS sent to {phone_number}: {result}")
                logging.info(f"SMS sent to {phone_number}: {result}")
                return result
            except requests.exceptions.HTTPError as e:
                if attempt == max_retries - 1:
                    print(f"Failed to send SMS to {phone_number} after {max_retries} attempts: {e}")
                    print(f"Response: {response.text}")
                    logging.error(f"Failed to send SMS to {phone_number}: {e}, Response: {response.text}")
                    return None
                time.sleep(1)
    except Exception as e:
        print(f"Failed to process SMS for {phone_number}: {e}")
        logging.error(f"Failed to process SMS for {phone_number}: {e}")
        return None

# ... existing code ...

# GUI Setup
root = tk.Tk()
root.title("Queue Management System")
root.attributes('-fullscreen', False)
root.configure(bg='white')

screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()

frame_style = {"bd": 0, "relief": "flat", "highlightthickness": 1, "highlightbackground": "lightgray"}

# Customer message frame
customer_message_width = int(screen_width * 0.98)
customer_message_padding = 0
customer_message = tk.Frame(root, width=customer_message_width, height=int(screen_height))
customer_message.place(x=customer_message_padding, y=int(screen_height * 0.93))

message_label = tk.Label(customer_message, text="  DEAR CUSTOMER, WE ARE PLEASED TO SERVE YOU. KINDLY SIT AND WAIT WHILE WE ARE SERVING OTHER CUSTOMERS  ", font=("roboto", int(screen_height * 0.025), "bold"), fg="white", bg="green", justify="center")
message_label.pack(fill=tk.BOTH, expand=True)

# Counter frames
num_counters = 4
counter_frame_width = int(screen_width * 0.1)
counter_frame_height = int(screen_height * 0.1)
counter_spacing = int(screen_width * 0.03)
counter_x_start = screen_width - counter_frame_width * 1.1
counter_y = 0

token_number_labels = []

def create_counter_frame(counter_id):
    # Calculate position from left to right
    counter_frame = tk.Frame(root, width=counter_frame_width, height=counter_frame_height, bg="lightgreen")
    counter_frame.place(x=counter_x_start - (num_counters - counter_id) * (counter_frame_width + counter_spacing), y=counter_y + 50)

    counter_label = tk.Label(counter_frame, text=f"Counter\n{counter_id}", font=("calibri", int(screen_height * 0.03), "bold"), fg="black", bg="lightgreen")
    counter_label.pack(fill=tk.BOTH, expand=True)
    counter_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    now_serving_frame = tk.Frame(root, width=counter_frame_width, height=int(counter_frame_height / 2), bg="lightgreen")
    now_serving_frame.place(x=counter_x_start - (num_counters - counter_id) * (counter_frame_width + counter_spacing), y=counter_y + counter_frame_height + 65)

    now_serving_label = tk.Label(now_serving_frame, text="NOW SERVING", fg="white", font=("Arial", int(screen_height * 0.018), "bold"), bg="green")
    now_serving_label.pack(fill=tk.BOTH, expand=True)

    token_frame = tk.Frame(root, width=counter_frame_width, height=int(counter_frame_height * 1.5), **frame_style)
    token_frame.place(x=counter_x_start - (num_counters - counter_id) * (counter_frame_width + counter_spacing), y=counter_y + counter_frame_height * 2.5)

    token_number_label = tk.Label(token_frame, text="", font=("calibri", int(screen_height * 0.07), "bold"), fg="black")
    token_number_label.pack(fill=tk.BOTH, expand=True)
    token_number_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
    token_number_labels.append(token_number_label)

    next_button = tk.Button(root, text="Next", command=lambda: handle_next_button(f"counter{counter_id}"))
    reset_button = tk.Button(root, text=f"Reset Counter {counter_id}", command=lambda: reset_counter(f"counter{counter_id}"), font=("Arial", int(screen_height * 0.02), "bold"), bg="orange", fg="white")

def on_key_press(event):
    key = event.char.lower()
    if key == 'd':
        # Get the current token from counter1's label
        counter_index = 0  # counter1 is at index 0
        current_token = token_number_labels[counter_index].cget("text")
        
        # If there's no token yet, start from 1, otherwise increment
        if not current_token:
            next_token = 1
        else:
            next_token = int(current_token) + 1
        
        # Update the counter with the new token
        update_counter('counter1', next_token)
        
        # Log the update
        logging.info(f"Counter 1 token incremented to {next_token}")

        # Send SMS to the phone number associated with the token being served
        # Find the token in the queue
        for q in queue:
            if q["token"] == next_token:
                phone = q["phone"]
                send_sms(phone, f"Now is your time to be served. Please proceed to the counter.")
                logging.info(f"Sent 'now is your time' SMS to {phone} for token {next_token}")
                break
        
    elif key == 'a':
        reset_counter('counter1')

root.bind("<Key>", on_key_press)

# Create counter frames
for i in range(1, num_counters + 1):
    create_counter_frame(i)

# Video frame
video_frame = tk.Label(root, bg="white")
video_frame.place(x=0, y=0, width=int(screen_width * 0.5), height=int(screen_height * 0.43))

# Set the path to the video file
video_path = r"D:\aluta\FYP\Documentation\videoplayback.mp4"
cap = cv2.VideoCapture(video_path)

def play_video():
    ret, frame = cap.read()
    if not ret:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        return
    
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    frame = cv2.resize(frame, (int(screen_width * 0.4999), int(screen_height * 0.44)))
    img = ImageTk.PhotoImage(Image.fromarray(frame))
    
    video_frame.img = img
    video_frame.config(image=img)
    
    root.after(30, play_video)

# Start video playback
play_video()

# Currency exchange rates
API_KEY = 'fca_live_mYsEF4trK4HJtYz6voDrrO5663krEJewkSMnRYMY'

def update_prices():
    headers = {'apikey': API_KEY}
    api_endpoint = 'https://api.freecurrencyapi.com/v1/latest'
    params = {'apikey': API_KEY, 'currencies': ','.join(currencies)}
    response = requests.get(api_endpoint, headers=headers, params=params)
    data = response.json()
    
    if 'data' in data:
        currency_data = data['data']
        usd_to_tzs = 2600
        spread_percentage = 2.0 / 100.0
        
        for i, currency in enumerate(currencies):
            if currency in currency_data:
                exchange_rate_to_usd = currency_data[currency]
                if currency == 'USD':
                    base_price_tzs = usd_to_tzs
                else:
                    base_price_tzs = usd_to_tzs / exchange_rate_to_usd
                
                buy_price_tzs = base_price_tzs * (1 - spread_percentage)
                sell_price_tzs = base_price_tzs * (1 + spread_percentage)
                
                buy_labels[i].config(text=f"{buy_price_tzs:.2f}")
                sell_labels[i].config(text=f"{sell_price_tzs:.2f}")
    
    root.after(300000, update_prices)  # Update every 5 minutes

# Currency frame
currency_frame_width = int(screen_width)
currency_frame_height = int(screen_height * 0.48)
currency_frame = tk.Frame(root, width=currency_frame_width, height=currency_frame_height, bg="white")
currency_frame.place(x=0, y=screen_height * 0.43)

column_width = currency_frame_width // 3

currency_label = tk.Label(currency_frame, text="CURRENCY", bg="green", font=("Arial", int(screen_height * 0.026), "bold"), fg="black")
currency_label.place(x=0, y=0, width=column_width)

buy_label = tk.Label(currency_frame, text="BUY", bg="green", font=("Arial", int(screen_height * 0.026), "bold"), fg="black")
buy_label.place(x=column_width, y=0, width=column_width)

sell_label = tk.Label(currency_frame, text="SELL", bg="green", font=("Arial", int(screen_height * 0.026), "bold"), fg="black")
sell_label.place(x=2 * column_width, y=0, width=column_width)

currencies = ['USD', 'EUR', 'GBP', 'JPY', 'CAD', 'CNY', 'CHF', 'AUD']
currency_labels = []
for i, currency in enumerate(currencies):
    label = tk.Label(currency_frame, text=currency, bg="lightgreen", font=("Arial", int(screen_height * 0.025)), fg="black")
    label.place(x=0, y=int(screen_height * 0.055) * (i+1), width=column_width)
    currency_labels.append(label)

buy_labels = []
for i in range(len(currencies)):
    label = tk.Label(currency_frame, text="", bg="lightgreen", font=("Arial", int(screen_height * 0.025)), fg="black")
    label.place(x=column_width, y=int(screen_height * 0.055) * (i+1), width=column_width)
    buy_labels.append(label)

sell_labels = []
for i in range(len(currencies)):
    label = tk.Label(currency_frame, text="", bg="lightgreen", font=("Arial", int(screen_height * 0.025)), fg="black")
    label.place(x=2 * column_width, y=int(screen_height * 0.055) * (i+1), width=column_width)
    sell_labels.append(label)

# Firebase Database References
counters_ref = db.reference('counters')
tokens_ref = db.reference('tokens')
returned_tokens_ref = db.reference('returned_tokens')

# Function to update token labels
def update_token_labels():
    def on_counter_change(event):
        try:
            counter_data = event.data
            if counter_data:
                for counter_id, data in counter_data.items():
                    if isinstance(data, dict):
                        counter_index = int(counter_id.split('counter')[1]) - 1
                        if data.get('token') is not None:
                            token_number_labels[counter_index].config(text=str(data['token']))
                            # Log the update
                            logging.info(f"Counter {counter_id} updated to token {data['token']}")
                        else:
                            token_number_labels[counter_index].config(text="")
                            logging.info(f"Counter {counter_id} cleared")
        except Exception as e:
            logging.error(f"Error updating token labels: {e}")
    
    try:
        counters_ref.listen(on_counter_change)
        logging.info("Token label listener started")
    except Exception as e:
        logging.error(f"Error starting token label listener: {e}")

# Function to get the next token number
def get_next_token():
    tokens = tokens_ref.get()
    if tokens:
        last_token = max(int(token_id) for token_id in tokens.keys())
        return last_token + 1
    return 101  # Starting token number

# Function to insert a new token
def insert_token(token_number):
    tokens_ref.child(str(token_number)).set({
        'status': 'waiting',
        'assigned_counter': None
    })

# Function to update a counter with a new token
def update_counter(counter_id, token_number):
    try:
        # Update Firebase
        counters_ref.child(counter_id).update({
            'token': token_number,
            'status': 'serving',
            'last_updated': time.time()
        })
        
        # Update token status
        tokens_ref.child(str(token_number)).update({
            'assigned_counter': counter_id,
            'status': 'serving',
            'served_at': time.time()
        })
        
        # Update UI
        root.after(0, lambda: update_token_label(counter_id, token_number))
        
        logging.info(f"Counter {counter_id} updated with token {token_number}")
    except Exception as e:
        logging.error(f"Error updating counter {counter_id}: {e}")
        print(f"Error updating counter {counter_id}: {e}")

# Function to update token label in UI
def update_token_label(counter_id, token_number):
    try:
        counter_index = int(counter_id.split('counter')[1]) - 1
        token_number_labels[counter_index].config(text=str(token_number))
        logging.info(f"UI updated: Counter {counter_id} showing token {token_number}")
    except Exception as e:
        logging.error(f"Error updating token label: {e}")
        print(f"Error updating token label: {e}")

# Function to reset a counter
def reset_counter(counter_id):
    counters_ref.child(counter_id).update({
        'token': None,
        'status': 'waiting'
    })
    print(f"Counter {counter_id} has been reset.")
    logging.info(f"Counter {counter_id} has been reset.")
    counter_index = int(counter_id[-1]) - 1
    token_number_labels[counter_index].config(text="")

# Function to reset the entire database
def reset_database():
    counters_ref.set({
        'counter1': {'token': None, 'status': 'waiting'},
        'counter2': {'token': None, 'status': 'waiting'},
        'counter3': {'token': None, 'status': 'waiting'},
        'counter4': {'token': None, 'status': 'waiting'}
    })
    tokens_ref.set({})
    returned_tokens_ref.set({})
    print("Database reset.")
    logging.info("Database reset.")

# Function to mark a token as returned
def mark_as_returned(counter_id):
    counter_data = counters_ref.child(counter_id).get()
    if counter_data and counter_data['token']:
        token_number = counter_data['token']
        returned_tokens_ref.child(str(token_number)).set({
            'status': 'returned'
        })
        tokens_ref.child(str(token_number)).update({
            'status': 'returned'
        })
        reset_counter(counter_id)
        print(f"Token {token_number} marked as returned")
        logging.info(f"Token {token_number} marked as returned")

# Function to serve a returned token
def serve_returned_token(counter_id):
    returned_tokens = returned_tokens_ref.get()
    if returned_tokens:
        for token_number in returned_tokens.keys():
            token_data = tokens_ref.child(token_number).get()
            if token_data and token_data['status'] == 'returned':
                update_counter(counter_id, int(token_number))
                returned_tokens_ref.child(token_number).delete()
                print(f"Counter {counter_id} serving returned token {token_number}")
                logging.info(f"Counter {counter_id} serving returned token {token_number}")
                break

# Function to handle the "Next" button click or ESP signal
def handle_next_button(counter_id):
    try:
        if queue:
            next_token_data = queue.pop(0)
            next_token = next_token_data["token"]
            phone = next_token_data["phone"]

            # Update Firebase database
            update_counter(counter_id, next_token)
            
            # Update UI
            root.after(0, lambda: update_token_label(counter_id, next_token))

            # Play audio announcement
            play_audio_sequence(next_token, counter_id.split('counter')[1], 'English')

            # Send SMS notification
            send_sms(phone, f"Your token {next_token} is now being served at {counter_id}.")

            # Log the action
            logging.info(f"Counter {counter_id} now serving token {next_token}")
            print(f"Counter {counter_id} now serving token {next_token}")

            # Update queue positions for remaining customers
            for i, q in enumerate(queue[:3]):  # Check first 3 positions
                if i < 2:  # Only notify if 1 or 2 positions away
                    send_sms(q["phone"], f"ALERT: Token {q['token']} is {i+1} positions away!")
        else:
            logging.info(f"No tokens in the queue for Counter {counter_id}")
            print(f"No tokens in the queue for Counter {counter_id}")
    except Exception as e:
        logging.error(f"Error in handle_next_button: {e}")
        print(f"Error in handle_next_button: {e}")

# Function to play audio sequence
def play_audio_sequence(token, counter, language):
    audio_directory = r"C:\Users\Administrator\Desktop\2021-04-01961\QueingSystem BRIQ INTREGRATION CODE\Documentation\audios"
    language_folder = os.path.join(audio_directory, language)
    tens = token // 10 * 10
    units = token % 10

    if 10 < token < 20 and language == 'English':
        audio_sequence = [
            "bell.mp3",
            "MtejaNamba.mp3",
            f"nam{token}.mp3",
            "TafadhaliElekeaDirishaNamba.mp3",
            f"counter_{counter}.mp3",
        ]
    else:
        if units == 0:
            audio_sequence = [
                "bell.mp3",
                "MtejaNamba.mp3",
                f"nam{tens}.mp3",
                "TafadhaliElekeaDirishaNamba.mp3",
                f"counter_{counter}.mp3",
            ]
        else:
            audio_sequence = [
                "bell.mp3",
                "MtejaNamba.mp3",
                f"nam{tens}.mp3",
                f"nam{units}.mp3",
                "TafadhaliElekeaDirishaNamba.mp3",
                f"counter_{counter}.mp3",
            ]
    
    for audio_file in audio_sequence:
        audio_path = os.path.join(language_folder, audio_file)
        pygame.mixer.music.load(audio_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)

# Initialize pygame mixer
pygame.mixer.init()

# Update prices and token labels
update_prices()
update_token_labels()

# Start the main event loop
root.mainloop() 