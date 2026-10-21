import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import SelectKBest, f_classif
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, accuracy_score


data = pd.read_csv(
    r"C:\Users\2026\Documents\Classroom\GitHub\learning-lab\ai-intern-smartED\Titanic-Dataset.csv"
)
# print(data.head())
data = data.drop(["Name", "Ticket", "Cabin"], axis=1)   # irrelevant/unique columns
data = pd.get_dummies(data, drop_first=True)            # categorical -> numeric
X = data.drop("Survived", axis=1)                       # features
y = data["Survived"]                                    # target

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42)

pipe = Pipeline([
    ("imputer", SimpleImputer(strategy="mean")),
    ("scaler", StandardScaler()),
    ("selector", SelectKBest(f_classif, k=5)),
    ("classifier", RandomForestClassifier())
])

param_grid = [
    {"classifier": [RandomForestClassifier()],
     "classifier__n_estimators": [50, 100, 200],
     "classifier__max_depth": [3, 5, 10]},
    {"classifier": [LogisticRegression(max_iter=500)],
     "classifier__C": [0.1, 1, 10]}
]

grid = GridSearchCV(pipe, param_grid, cv=5, scoring="accuracy")
grid.fit(X_train, y_train)

print("Best model:", grid.best_estimator_)
print("Best params:", grid.best_params_)

y_pred = grid.predict(X_test)
print(classification_report(y_test, y_pred))
print("Accuracy:", accuracy_score(y_test, y_pred))
