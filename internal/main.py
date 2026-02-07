from fastapi import FastAPI

app = FastAPI()

@app.get("/hobbies")
def hobbies():
    return {
        "service": "internal-api",
        "hobbies": ["running", "gym", "painting and/or sketching", "reading books", "creating cloud and devops README.md tutorials (very new to this though)"]
    }

@app.get("/secrets")
def secrets():
    return {
        "service": "internal-api",
        "secrets": [
            "I sometimes talk to my terminal to speed up builds.", 
            "I secretly enjoy deleting unused AWS resources more than deploying apps.",
            "I am spiderman.",
            "I am a genius billionaire playboy philanthropist by day, and a masked vigilante by night."
            ]
    }