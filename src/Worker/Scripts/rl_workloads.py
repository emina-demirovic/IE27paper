"""CPU Q-learning workloads for the distributed experiment Worker."""

import json
import sys
from collections import defaultdict
from contextlib import closing

import gymnasium as gym
import numpy as np


def state_encoder(state_bins):
    if not state_bins:
        # Blackjack returns a hashable tuple; FrozenLake and Taxi return integers.
        return lambda observation: observation
    lower, upper, bins = np.array(state_bins).T
    scale = bins / (upper - lower)

    def encode(observation):
        return tuple(np.clip((observation - lower) * scale, 0, bins - 1).astype(int))

    return encode


def write_event(prefix, payload):
    print(prefix + json.dumps(payload, allow_nan=False), flush=True)


def train(env, env_id, max_steps, seed, state_bins):
    rng = np.random.default_rng(seed)
    encode = state_encoder(state_bins)
    if env_id == "Pendulum-v1":
        actions = [np.array([torque], dtype=np.float32) for torque in (-2, -1, 0, 1, 2)]
    else:
        actions = range(env.action_space.n)

    q_values = defaultdict(lambda: np.zeros(len(actions)))
    observation, _ = env.reset(seed=seed)
    state = encode(observation)
    episodes = 0
    episode_return = completed_return = total_reward = 0.0
    report_steps = {max(1, max_steps * quarter // 4) for quarter in range(1, 5)}

    for step in range(1, max_steps + 1):
        values = q_values[state]
        epsilon = max(0.05, 1 - (step - 1) / (0.8 * max_steps))
        if rng.random() < epsilon:
            action = rng.integers(len(actions))
        else:
            action = rng.choice(np.flatnonzero(values == values.max()))

        observation, reward, terminated, truncated, _ = env.step(actions[action])
        next_state = encode(observation)
        # Time-limit truncation resets the episode but retains the bootstrap value.
        target = reward if terminated else reward + 0.99 * q_values[next_state].max()
        values[action] += 0.1 * (target - values[action])
        episode_return += reward
        total_reward += reward

        if terminated or truncated:
            completed_return += episode_return
            episodes += 1
            episode_return = 0.0
            if step < max_steps:
                observation, _ = env.reset()
                next_state = encode(observation)
        state = next_state

        if step in report_steps:
            write_event("PROGRESS_JSON:", {
                "currentStep": step,
                "metrics": {"episodes": episodes, "total_reward": total_reward},
            })

    return {
        "algorithm": "q-learning", "environment": env_id, "seed": seed,
        "steps": max_steps, "episodes": episodes, "total_reward": total_reward,
        "mean_completed_episode_return": completed_return / episodes if episodes else None,
        "visited_states": len(q_values),
    }


def run_q_learning(args, environments, state_bins):
    env_id = environments.get(args.environment.strip().casefold())
    if env_id is None or args.max_steps < 1:
        print(f"Unknown RL environment or invalid step budget: {args.environment}, {args.max_steps}",
              file=sys.stderr)
        return 1
    if args.simulate_failure:
        print("Intentional RL experiment failure.", file=sys.stderr)
        return 1
    with closing(gym.make(env_id)) as env:
        metrics = train(env, env_id, args.max_steps, args.seed % (2**32), state_bins.get(env_id))
    write_event("RESULT_JSON:", metrics)
    return 0
