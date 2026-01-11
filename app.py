import threading

from flask import Flask, jsonify, request

from main import run_main

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
    worker = threading.Thread(target=run_main, daemon=True)
    worker.start()
    return "✅ Đã bắt đầu chạy GetTextFromLink!", 202


if __name__ == '__main__':
    app.run(debug=True, port=5000)
