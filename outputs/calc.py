import sys

def add(a, b):
    return a + b

def main():
    if len(sys.argv) != 3:
        print("Usage: python calc.py <num1> <num2>")
        sys.exit(1)
    try:
        num1 = float(sys.argv[1])
        num2 = float(sys.argv[2])
    except ValueError:
        print("Please provide valid numbers")
        sys.exit(1)
    result = add(num1, num2)
    # If result is integer, print as int else float
    if result.is_integer():
        print(int(result))
    else:
        print(result)

if __name__ == "__main__":
    main()