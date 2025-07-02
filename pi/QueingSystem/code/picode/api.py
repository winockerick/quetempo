from flask import Flask, request, jsonify
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, db
import logging
import os
from dotenv import load_dotenv

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Configure logging
log_dir = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, 'api.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

# Initialize Firebase
cred = credentials.Certificate("D:/aluta/FYP/QueingSystem/code/picode/credentials/serviceAccountKey.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://beqs-651fc-default-rtdb.firebaseio.com/'
})

# Firebase Database References
counters_ref = db.reference('counters')
tokens_ref = db.reference('tokens')
returned_tokens_ref = db.reference('returned_tokens')

@app.route('/api/token', methods=['POST'])
def create_token():
    try:
        data = request.json
        phone = data.get('phone')
        token_type = data.get('type', 'regular')
        
        if not phone:
            return jsonify({'error': 'Phone number is required'}), 400
            
        # Get next token number
        tokens = tokens_ref.get()
        if tokens:
            last_token = max(int(token_id) for token_id in tokens.keys())
            next_token = last_token + 1
        else:
            next_token = 101  # Starting token number
            
        # Insert token into Firebase
        tokens_ref.child(str(next_token)).set({
            'status': 'waiting',
            'assigned_counter': None,
            'phone': phone,
            'type': token_type
        })
        
        logging.info(f"New token {next_token} created for phone {phone}")
        
        return jsonify({
            'success': True,
            'token': next_token,
            'message': f'Token {next_token} has been created'
        })
        
    except Exception as e:
        logging.error(f"Error creating token: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/token/<token_number>', methods=['GET'])
def get_token_status(token_number):
    try:
        token_data = tokens_ref.child(token_number).get()
        if not token_data:
            return jsonify({'error': 'Token not found'}), 404
            
        return jsonify({
            'success': True,
            'token': int(token_number),
            'status': token_data.get('status'),
            'assigned_counter': token_data.get('assigned_counter'),
            'phone': token_data.get('phone'),
            'type': token_data.get('type')
        })
        
    except Exception as e:
        logging.error(f"Error getting token status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/counters', methods=['GET'])
def get_counters():
    try:
        counters = counters_ref.get()
        return jsonify({
            'success': True,
            'counters': counters
        })
        
    except Exception as e:
        logging.error(f"Error getting counters: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/queue', methods=['GET'])
def get_queue():
    try:
        tokens = tokens_ref.get()
        if not tokens:
            return jsonify({'queue': []})
            
        # Filter waiting tokens and sort by type (priority first)
        queue = []
        for token_id, data in tokens.items():
            if data.get('status') == 'waiting':
                queue.append({
                    'token': int(token_id),
                    'phone': data.get('phone'),
                    'type': data.get('type', 'regular')
                })
                
        # Sort queue by type (priority first)
        queue.sort(key=lambda x: 0 if x['type'].lower() == 'priority' else 1)
        
        return jsonify({
            'success': True,
            'queue': queue
        })
        
    except Exception as e:
        logging.error(f"Error getting queue: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000) 