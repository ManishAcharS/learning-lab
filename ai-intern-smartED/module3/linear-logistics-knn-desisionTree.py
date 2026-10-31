import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, mean_squared_error
from sklearn.tree import DecisionTreeClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.datasets import make_regression, load_iris
X_reg, y_reg = make_regression(n_samples=100, n_features=1, noise=10, random_state=42)
Xr_train, Xr_test, yr_train, yr_test = train_test_split(X_reg, y_reg, test_size=0.2, random_state=42)
#Linear Regression
lin_model = LinearRegression()
lin_model.fit(Xr_train, yr_train)
y_pred = lin_model.predict(Xr_test)
print("MSE:", mean_squared_error(yr_test, y_pred))
#Iris dataset
iris = load_iris()
X, y = iris.data, iris.target   # features: sepal/petal length and width; classes: 3 species
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
#Logistic Regression
log_model = LogisticRegression(max_iter=200)   # max_iter ensures convergence
log_model.fit(X_train, y_train)
print("Accuracy:", accuracy_score(y_test, log_model.predict(X_test)))
#Decision Tree Classifier
tree_model = DecisionTreeClassifier(max_depth=3, random_state=42)
tree_model.fit(X_train, y_train)
print("Accuracy:", accuracy_score(y_test, tree_model.predict(X_test)))
#KNN
knn_model = KNeighborsClassifier(n_neighbors=5)
knn_model.fit(X_train, y_train)
print("Accuracy:", accuracy_score(y_test, knn_model.predict(X_test)))
