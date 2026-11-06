# Step 1: Imports
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Flatten
from tensorflow.keras.datasets import mnist
from tensorflow.keras.utils import to_categorical
from tensorflow.keras.layers import Input

# Step 2: Load data (60,000 train / 10,000 test, 28x28 grayscale)
(X_train, y_train), (X_test, y_test) = mnist.load_data()

# Step 3: Normalize pixels from 0-255 to 0-1
X_train = X_train / 255.0
X_test = X_test / 255.0

# Step 4: One-hot encode labels (e.g. 3 -> [0,0,0,1,0,0,0,0,0,0])
y_train = to_categorical(y_train, 10)
y_test = to_categorical(y_test, 10)

# Step 5: Build the model (Flatten 28x28 -> 784, hidden layer, 10-class softmax output)
model = Sequential([
    Input(shape=(28, 28)),
    Flatten(),
    Dense(128, activation="relu"),
    Dense(10, activation="softmax")
])

# Step 6: Compile with Adam optimizer and categorical cross-entropy loss
model.compile(optimizer="adam",
              loss="categorical_crossentropy",
              metrics=["accuracy"])

# Step 7: Train (1 epoch = full pass; 60,000 / 32 = 1,875 steps per epoch)
history = model.fit(X_train, y_train, epochs=5, batch_size=32,
                    validation_data=(X_test, y_test))

# Step 8: Evaluate on the test set
loss, acc = model.evaluate(X_test, y_test)
print("Test accuracy:", acc)

# Predict first 5 test images and compare predicted vs true labels
preds = model.predict(X_test[:5])
print(preds.argmax(axis=1), y_test[:5].argmax(axis=1))
