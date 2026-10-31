#Step 1: Imports

import numpy as np
import matplotlib.pyplot as plt
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
#Step 2: Synthetic data
np.random.seed(42)
n_samples = 30
X = np.linspace(0, 1, n_samples)
y = np.sin(2 * np.pi * X) + np.random.normal(0, 0.2, n_samples)
X = X.reshape(-1, 1)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)
#Step 3: Fit polynomial models of different degrees
def fit_poly(degree):
    poly = PolynomialFeatures(degree)
    Xtr = poly.fit_transform(X_train)
    Xte = poly.transform(X_test)
    model = LinearRegression().fit(Xtr, y_train)
    train_err = mean_squared_error(y_train, model.predict(Xtr))
    test_err = mean_squared_error(y_test, model.predict(Xte))
    return train_err, test_err
#Step 4: Compare degrees
degrees = range(1, 16)
train_errors, test_errors = [], []
for d in degrees:
    tr, te = fit_poly(d)
    train_errors.append(tr)
    test_errors.append(te)

plt.plot(degrees, train_errors, label="Train error")
plt.plot(degrees, test_errors, label="Test error")
plt.xlabel("Polynomial degree (model complexity)")
plt.ylabel("MSE")
plt.legend()
plt.show()
