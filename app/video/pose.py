import numpy as np

BODY_INDICES = [0, 11, 12, 13, 14, 15, 16]
FEATURE_DIM = 49 * 4
POSE_SCHEMA = "mp_tasks_49x4_shoulder_v1"


def normalize_landmarks(points):
    points = np.asarray(points, dtype=np.float32).reshape(49, 4).copy()
    if points[1, 3] > 0.3 and points[2, 3] > 0.3:
        center = (points[1, :3] + points[2, :3]) / 2
        scale = max(float(np.linalg.norm(points[1, :2] - points[2, :2])), 0.08)
        present = points[:, 3] > 0
        points[present, :3] = (points[present, :3] - center) / scale
    return np.clip(points, -8, 8).ravel()


class PoseExtractor:
    def __init__(self, hand_path, body_path):
        import mediapipe as mp
        self.mp = mp
        base = mp.tasks.BaseOptions
        vision = mp.tasks.vision
        self.hands = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=base(model_asset_path=str(hand_path)), num_hands=2))
        self.body = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
            base_options=base(model_asset_path=str(body_path)), num_poses=1))

    def extract(self, rgb):
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        hands = self.hands.detect(image)
        body = self.body.detect(image)
        points = np.zeros((49, 4), np.float32)
        if body.pose_landmarks:
            for j, index in enumerate(BODY_INDICES):
                p = body.pose_landmarks[0][index]
                points[j] = [p.x, p.y, p.z, p.visibility]
        for hand, label in zip(hands.hand_landmarks, hands.handedness):
            offset = 7 if label[0].category_name == "Left" else 28
            for j, p in enumerate(hand):
                points[offset + j] = [p.x, p.y, p.z, label[0].score]
        return normalize_landmarks(points), points

    def close(self):
        self.hands.close()
        self.body.close()
