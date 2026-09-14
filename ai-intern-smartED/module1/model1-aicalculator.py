import numpy as np
def input_matrix(name):
    print(f"Enter values for {name} matrix :")
    try:
        return np.array(eval(input()))
    except Exception as e:
        print("\nplease enter it again...")
        return input_matrix(name)
def input_vector(name):
    print(f"Enter values for {name} vector :")
    try:
        return np.array(eval(input()))
    except Exception as e:
        print("\nplease enter it again...")
        return input_vector(name)
def matrix_multiply(A, B):
    try:
        return np.dot(A, B)
    except Exception as e:
        print(f"\nerror: {e}")
def vector_dot(v1,v2):
    try:
        return np.dot(v1, v2)
    except Exception as e:
        print(f"\nerror: {e}")
def sigmoid(x):
    return 1 / (1 + np.exp(-x))
def relu(x):
    return np.maximum(0,x)
def softmax(x):
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum()
def options():
    print("1. Matrix Multiplication")
    print("2. Vector Dot Product")
    print("3. Sigmoid Function")
    print("4. ReLU Function")
    print("5. Softmax Function")
    print("6. Exit")
def run_calculator():
    print("AI Math Calculator")
    while True:
        options()
        choice = input("\n\n\nEnter your choice (1-6): ")
        match choice:
            case "1":
                A = input_matrix("A")
                B = input_matrix("B")
                result = matrix_multiply(A, B)
                print("\nResult of Matrix Multiplication:")
                print(result)
            case "2":
                v1 = input_vector("v1")
                v2 = input_vector("v2")
                result = vector_dot(v1, v2)
                print("\nResult of Vector Dot Product:")
                print(result)
            case "3":
                x = input_vector("x")
                result = sigmoid(x)
                print("\nResult of Sigmoid Function:")
                print(result)
            case "4":
                x = input_vector("x")
                result = relu(x)
                print("\nResult of ReLU Function:")
                print(result)
            case "5":
                x = input_vector("x")
                result = softmax(x)
                print("\nResult of Softmax Function:")
                print(result)
            case "6":
                print("\nExiting...,Thank you :)")
                break
            case _:
                print("\nInvalid choice. Please enter a valid option.")

if __name__ == "__main__":
    run_calculator()
