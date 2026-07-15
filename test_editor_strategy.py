
import time
import random

def main():
    """Test strategy for editor functionality"""
    print("Test strategy started")
    
    while True:
        # Simulate trading logic
        price = random.uniform(100, 200)
        print(f"Current price: {price:.2f}")
        
        # Sleep for a bit
        time.sleep(5)
        
        # Check for stop condition
        if random.random() < 0.1:
            print("Strategy stopping...")
            break
    
    print("Strategy completed")

if __name__ == "__main__":
    main()
