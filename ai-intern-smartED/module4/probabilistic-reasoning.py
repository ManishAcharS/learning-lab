# ---------- Joint probability table ----------
import numpy as np
import pandas as pd

# Joint probabilities of weather and umbrella use (must sum to 1)
data = [
    ("Rain, Umbrella", 0.30),
    ("Rain, No Umbrella", 0.20),
    ("No Rain, Umbrella", 0.20),
    ("No Rain, No Umbrella", 0.30),
]
# Put the events and their probabilities in a table
df = pd.DataFrame(data, columns=["Event", "Probability"])
print(df)


# ---------- Marginal and conditional probability ----------
# Marginal: add up all joint cells where it rains
P_rain = 0.30 + 0.20
# Marginal: add up all joint cells where an umbrella is carried
P_umbrella = 0.30 + 0.20
# Joint: rain and umbrella together
P_rain_and_umbrella = 0.30

# Conditional: P(Rain | Umbrella) = P(Rain and Umbrella) / P(Umbrella)
P_rain_given_umbrella = P_rain_and_umbrella / P_umbrella
print("P(Rain | Umbrella) =", P_rain_given_umbrella)   # 0.6


# ---------- Bayes: medical test ----------
# Prior: 1% of people have the disease
P_D = 0.01
# Complement: 99% do not have it
P_notD = 1 - P_D
# Sensitivity: test is positive for 99% of sick people
P_pos_given_D = 0.99
# False positive rate: test is positive for 5% of healthy people
P_pos_given_notD = 0.05

# Total probability of a positive test
P_pos = P_pos_given_D * P_D + P_pos_given_notD * P_notD
# Bayes' theorem: P(Disease | Positive)
P_D_given_pos = (P_pos_given_D * P_D) / P_pos
print("P(Disease | Positive) =", round(P_D_given_pos, 3))   # about 0.167


# ---------- Bayes: card game ----------
# Probability a random card is a king
P_king = 4 / 52
# Probability a random card is a face card (J, Q, K)
P_face = 12 / 52
# Every king is a face card
P_face_given_king = 1
# Bayes' theorem: P(King | Face)
P_king_given_face = (P_face_given_king * P_king) / P_face
print(P_king_given_face)       # 0.333...


# ---------- Visualizing Bayesian updating ----------
import matplotlib.pyplot as plt

# Range of possible prior beliefs from 0 to 1
prior = np.linspace(0, 1, 100)
# Test sensitivity: P(Positive | Disease)
likelihood = 0.99
# False positive rate: P(Positive | No Disease)
false_positive = 0.05
# Posterior for every prior using Bayes' theorem
posterior = (likelihood * prior) / (likelihood * prior + false_positive * (1 - prior))

# Plot the updated belief against the prior
plt.plot(prior, posterior, label="Posterior after positive test")
# Dashed line shows no update (posterior = prior)
plt.plot(prior, prior, "--", label="Prior")
plt.xlabel("Prior belief P(Disease)")
plt.ylabel("Posterior P(Disease | Positive)")
plt.legend()
plt.show()
