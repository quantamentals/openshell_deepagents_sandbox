import random

def sum_two_random_numbers():
    """Generate two random numbers and return their sum."""
    # Generate two random numbers between 1 and 100
    num1 = random.randint(1, 100)
    num2 = random.randint(1, 100)
    
    # Calculate the sum
    result = num1 + num2
    
    # Print the numbers and their sum
    print(f"First random number: {num1}")
    print(f"Second random number: {num2}")
    print(f"Sum: {result}")
    
    return result

if __name__ == "__main__":
    sum_two_random_numbers()