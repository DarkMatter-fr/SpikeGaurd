try:
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    print("Successfully imported MediaPipe Tasks API!")
    print("Vision dir:", dir(vision))
except Exception as e:
    print("Failed to import MediaPipe Tasks API:", e)


