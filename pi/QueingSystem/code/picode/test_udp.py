import socket
import time

# UDP Test Client
UDP_IP = "127.0.0.1"  # localhost
UDP_PORT = 12345

def send_test_message(message):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(message.encode(), (UDP_IP, UDP_PORT))
        print(f"✅ Sent: {message}")
    except Exception as e:
        print(f"❌ Error sending: {e}")
    finally:
        sock.close()

if __name__ == "__main__":
    print("🧪 UDP Test Client")
    print("=" * 30)
    
    # Test messages
    test_messages = [
        "TOKENIZER,0712345678,101,normal",
        "TOKENIZER,0755555555,102,priority", 
        "0626551833,2,regular",  # Direct format without prefix
        "0755123456,15,priority",  # Direct format without prefix
        "TELLER,D",
        "TELLER,*",
        "TELLER,#",
        "#"
    ]
    
    for i, message in enumerate(test_messages, 1):
        print(f"\n{i}. Testing: {message}")
        send_test_message(message)
        time.sleep(1)  # Wait 1 second between messages
    
    print("\n✅ Test completed!") 