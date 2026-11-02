# ---------- Step 1: Install and import ----------
# Install the required libraries (notebook command)

import pandas as pd
# Splits data into training and test sets
from sklearn.model_selection import train_test_split
# Converts text into word-count vectors (Bag of Words)
from sklearn.feature_extraction.text import CountVectorizer
# Naive Bayes classifier for count data
from sklearn.naive_bayes import MultinomialNB
# Tools to measure model performance
from sklearn.metrics import accuracy_score, confusion_matrix, classification_report


# ---------- Step 2: Load the dataset (Kaggle "SMS Spam Collection", downloaded via kagglehub) ----------
# Read the CSV and keep only the label and message columns
data = pd.read_csv("spam.csv", encoding="latin-1")[["v1", "v2"]]
# Give the columns clear names
data.columns = ["label", "message"]
# Encode labels as numbers: ham = 0, spam = 1
data["label"] = data["label"].map({"ham": 0, "spam": 1})
print(data.shape)    # (5572, 2)
print(data.head())


# ---------- Step 3: Train/test split ----------
# Hold out 20% of messages for testing, with a fixed seed for reproducibility
X_train, X_test, y_train, y_test = train_test_split(
    data["message"], data["label"], test_size=0.2, random_state=42)


# ---------- Step 4: Bag of Words ----------
# Count word occurrences, ignoring common English stop words
vectorizer = CountVectorizer(stop_words="english")
# Learn the vocabulary from training data and convert it to counts
X_train_bow = vectorizer.fit_transform(X_train)
# Convert test data using the training vocabulary (transform only, never fit)
X_test_bow = vectorizer.transform(X_test)
print("Vocabulary size:", len(vectorizer.vocabulary_))   # about 7,472 in the demo
# Use fit_transform on training data but only transform on test data


# ---------- Step 5: Train ----------
# Create the Naive Bayes model
nb = MultinomialNB()
# Learn word probabilities for spam and ham from the training data
nb.fit(X_train_bow, y_train)


# ---------- Step 6: Predict and evaluate ----------
# Predict labels for the unseen test messages
y_pred = nb.predict(X_test_bow)
# Overall fraction of correct predictions
print("Accuracy:", accuracy_score(y_test, y_pred))
# Counts of true/false positives and negatives
print(confusion_matrix(y_test, y_pred))
# Precision, recall and F1 for each class
print(classification_report(y_test, y_pred))


# ---------- Step 7: Try your own messages ----------
# Two new messages to classify
msgs = ["Congratulations! You won a free iPhone", "Let's meet for the project discussion"]
# Vectorize with the same vocabulary, then predict
print(nb.predict(vectorizer.transform(msgs)))   # [1 0] -> spam, ham
