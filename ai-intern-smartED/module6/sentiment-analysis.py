
import re
import pandas as pd
import gradio as gr
import matplotlib.pyplot as plt

from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import MultinomialNB


# 1. Small labeled dataset
data = {
    "review": [
        "I love this product",
        "Amazing experience",
        "This is fantastic",
        "Very good quality",
        "I am happy with this",
        "Absolutely wonderful",
        "I hate this product",
        "Very bad experience",
        "This is terrible",
        "Worst quality ever",
        "I am disappointed",
        "Absolutely horrible"
    ],
    "sentiment": [
        "positive", "positive", "positive",
        "positive", "positive", "positive",
        "negative", "negative", "negative",
        "negative", "negative", "negative"
    ]
}

df = pd.DataFrame(data)


# 2. Clean text
def clean_text(text):
    text = text.lower()
    text = re.sub(r"[^a-z\s]", "", text)
    return text


df["clean"] = df["review"].apply(clean_text)


# 3. Logistic Regression pipeline
lr_pipeline = Pipeline([
    ("tfidf", TfidfVectorizer(stop_words="english")),
    ("clf", LogisticRegression(max_iter=200)),
])


# 4. Naive Bayes pipeline
nb_pipeline = Pipeline([
    ("tfidf", TfidfVectorizer(stop_words="english")),
    ("clf", MultinomialNB()),
])


# 5. Train both models
lr_pipeline.fit(df["clean"], df["sentiment"])
nb_pipeline.fit(df["clean"], df["sentiment"])

models = {
    "Logistic Regression": lr_pipeline,
    "Naive Bayes": nb_pipeline
}


# 6. Predict sentiment
def predict_sentiment(text, model_name):

    if not text.strip():
        return "Enter a review", None

    model = models[model_name]

    cleaned = clean_text(text)

    if not cleaned.strip():
        return "Enter meaningful text", None

    prediction = model.predict([cleaned])[0]

    probs = model.predict_proba([cleaned])[0]

    classes = model.classes_

    confidence = max(probs) * 100

    result = (
        f"Sentiment: {prediction.upper()}\n"
        f"Confidence: {confidence:.2f}%"
    )

    # Probability chart
    fig, ax = plt.subplots()

    ax.bar(classes, probs)
    ax.set_ylim(0, 1)
    ax.set_ylabel("Probability")
    ax.set_title("Sentiment Probability")

    plt.tight_layout()

    return result, fig


# 7. Gradio interface
with gr.Blocks() as demo:

    gr.Markdown("# AI Sentiment Analysis")

    text_input = gr.Textbox(
        label="Enter your review",
        placeholder="I love this product!"
    )

    model_choice = gr.Dropdown(
        choices=list(models.keys()),
        value="Logistic Regression",
        label="Select Model"
    )

    button = gr.Button("Predict Sentiment")

    result = gr.Textbox(label="Prediction")

    chart = gr.Plot(label="Probability Chart")

    button.click(
        predict_sentiment,
        inputs=[text_input, model_choice],
        outputs=[result, chart]
    )


# 8. Launch
demo.launch(share=True)
