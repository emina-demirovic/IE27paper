import numpy as np


ENVIRONMENTS = {
    "mountaincar": "MountainCar-v0",
    "acrobot": "Acrobot-v1",
    "pendulum": "Pendulum-v1",
    "lunarlander": "LunarLander-v3",
}

STATE_BINS = {
    "MountainCar-v0": [(-1.2, 0.6, 24), (-0.07, 0.07, 24)],
    "Acrobot-v1": [(-1, 1, 5)] * 4 + [(-4 * np.pi, 4 * np.pi, 9), (-9 * np.pi, 9 * np.pi, 9)],
    "Pendulum-v1": [(-1, 1, 12), (-1, 1, 12), (-8, 8, 17)],
    "LunarLander-v3": [
        (-1.5, 1.5, 7), (-0.25, 1.5, 7), (-2, 2, 7), (-2, 2, 7),
        (-np.pi, np.pi, 9), (-3, 3, 7), (0, 1, 2), (0, 1, 2),
    ],
}
