#Knowledge Base
knowledge_base = {
    "fever and cough": "flu",
    "headache and nausea": "migraine",
    "chest pain and shortness of breath": "heart disease"
}
#Inference Engine
def inference_engine(symptoms):
    for rule, disease in knowledge_base.items():
        conditions = rule.split(" and ")
        if all(c in symptoms for c in conditions):
            return disease
    return "No diagnosis found"
#User Interface
print("Welcome to the Medical Expert System")
user_input = input("Enter your symptoms separated by commas: ")
symptoms = [s.strip().lower() for s in user_input.split(",")]

diagnosis = inference_engine(symptoms)
print("Based on your symptoms, possible diagnosis:", diagnosis)
