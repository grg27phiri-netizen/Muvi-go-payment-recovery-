from app import init_db, app
init_db()
app.run(host='0.0.0.0', port=5000, debug=False)
