# Install Experta (run in Colab)
# !pip install experta
from experta import *

# Fact describing a plant symptom
class Symptom(Fact):
    pass

# Expert system with care rules
class PlantCareExpert(KnowledgeEngine):

    # Yellow leaves -> fertilizer
    @Rule(Symptom(name="yellow_leaves"))
    def fertilizer(self):
        print("Advice: Add fertilizer to the soil.")

    # Dry soil -> water
    @Rule(Symptom(name="dry_soil"))
    def water(self):
        print("Advice: Water the plant.")

    # Wilting -> more sunlight
    @Rule(Symptom(name="wilting"))
    def sunlight(self):
        print("Advice: Increase sunlight exposure.")

    # Leaf spots -> pesticide
    @Rule(Symptom(name="leaf_spots"))
    def pesticide(self):
        print("Advice: Apply pesticide.")

engine = PlantCareExpert()
engine.reset()                                  # Initialise the engine
engine.declare(Symptom(name="yellow_leaves"))   # Add observed facts
engine.declare(Symptom(name="dry_soil"))
engine.run()                                    # Fire matching rules (forward chaining)

# Simple dictionary knowledge base
knowledge_base = {
    "yellow_leaves": "Add fertilizer",
    "dry_soil": "Water the plant"
}
fact = "dry_soil"
print(knowledge_base.get(fact, "No rule found"))   # Default if no rule exists

# ---------------- ML Pipeline ----------------
import numpy as np
import pandas as pd

# Create synthetic dataset
np.random.seed(42)
n = 500
data = pd.DataFrame({
    "soil_moisture": np.random.uniform(0, 100, n),
    "sunlight_hours": np.random.uniform(0, 12, n),
    "fertilizer_level": np.random.uniform(0, 10, n),
    "pest_presence": np.random.choice([0, 1], n),
    "plant_health": np.random.choice([0, 1, 2], n)   # 0 healthy, 1 stressed, 2 diseased
})

# Split and scale data
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

X = data.drop("plant_health", axis=1)
y = data["plant_health"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)   # Fit on training data only
X_test_scaled = scaler.transform(X_test)

# Train three models and print accuracy
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.metrics import accuracy_score

models = {
    "Logistic Regression": LogisticRegression(max_iter=200),
    "Decision Tree": DecisionTreeClassifier(random_state=42),
    "KNN": KNeighborsClassifier(n_neighbors=5)
}
for name, m in models.items():
    m.fit(X_train_scaled, y_train)
    print(name, "accuracy:", accuracy_score(y_test, m.predict(X_test_scaled)))

# Bias-variance: tree depth vs accuracy
import matplotlib.pyplot as plt

depths = range(1, 16)
train_acc, test_acc = [], []
for d in depths:
    tree = DecisionTreeClassifier(max_depth=d, random_state=42)
    tree.fit(X_train_scaled, y_train)
    train_acc.append(tree.score(X_train_scaled, y_train))
    test_acc.append(tree.score(X_test_scaled, y_test))

plt.plot(depths, train_acc, label="Train")
plt.plot(depths, test_acc, label="Test")
plt.xlabel("Tree depth"); plt.ylabel("Accuracy"); plt.legend(); plt.show()

# Evaluate Logistic Regression
from sklearn.metrics import confusion_matrix, classification_report, roc_auc_score
from sklearn.preprocessing import label_binarize

y_pred = models["Logistic Regression"].predict(X_test_scaled)
print(confusion_matrix(y_test, y_pred))
print(classification_report(y_test, y_pred))   # Precision, recall, F1

# Multiclass ROC-AUC (one-vs-rest, micro average)
y_test_bin = label_binarize(y_test, classes=[0, 1, 2])
y_score = models["Logistic Regression"].predict_proba(X_test_scaled)
print("ROC-AUC:", roc_auc_score(y_test_bin, y_score, average="micro"))
