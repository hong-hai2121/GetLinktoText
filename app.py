from flask import Flask, request, jsonify
from Source.GetTextFromLink import run_main

app = Flask(__name__)

@app.route('/', methods=['GET'])
def home():
    return "🚀 Flask server is running!"

@app.route('/hello', methods=['POST'])
def hello():
    data = request.get_json()
    name = data.get("name", "bạn")
    return jsonify({"message": f"Xin chào {name}!"})

@app.route("/run-gettext", methods=["GET"])
def run_gettext():
    print("Đang chạy GetTextFromLink...")
    from Source.GetTextFromLink import run_main
    run_main()
    return "✅ Đã chạy xong GetTextFromLink!", 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)
