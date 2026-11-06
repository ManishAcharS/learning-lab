import numpy as np

# Data (XOR)
X = np.array([[0,0],[0,1],[1,0],[1,1]])
y = np.array([[0],[1],[1],[0]])

# Random initialization
np.random.seed(42)
W1 = np.random.randn(2, 2); b1 = np.zeros((1, 2))
W2 = np.random.randn(2, 1); b2 = np.zeros((1, 1))

def sigmoid(z): return 1 / (1 + np.exp(-z))
def sigmoid_derivative(a): return a * (1 - a)   # a = sigmoid(z)

lr = 0.1
for epoch in range(10000):
    # Forward pass
    a1 = sigmoid(X @ W1 + b1)
    a2 = sigmoid(a1 @ W2 + b2)

    # Loss (MSE)
    loss = np.mean((y - a2) ** 2)

    # Backward pass
    d2 = (a2 - y) * sigmoid_derivative(a2)
    d1 = (d2 @ W2.T) * sigmoid_derivative(a1)

    # Gradient descent updates
    W2 -= lr * a1.T @ d2;  b2 -= lr * d2.sum(axis=0, keepdims=True)
    W1 -= lr * X.T @ d1;   b1 -= lr * d1.sum(axis=0, keepdims=True)

    if epoch % 1000 == 0:
        print(f"Epoch {epoch}, Loss: {loss:.4f}")

print(np.round(a2, 3))
