---
name: robotics-sim
description: Domain knowledge for robotics simulation on the SHML platform. Covers the ROSMASTER M3 PRO target hardware, MuJoCo/Isaac Sim environments, drone simulation (Crazyflow/gym-pybullet-drones), ROS2 Nav2/SLAM, URDF/MJCF model pipelines, RL training with Ray, and sim-to-real transfer. Use when the user asks about robot sim, drone RL, MuJoCo envs, URDF conversion, ROS2, or the shml-robotics project.
license: MIT
compatibility: GitLab project 3 (shml/robotics). Requires GITLAB_PROJECT_ID=3 for issue operations. MuJoCo/Isaac Sim containers not yet deployed (Phase 1+). Drone sim frameworks installable via pip.
metadata:
  author: shml-platform
  version: "1.0"
activation_triggers:
  - mujoco
  - ros2
  - urdf
  - mjcf
  - isaac sim
  - drone
  - quadrotor
  - crazyflie
  - crazyflow
  - rl training
  - robotics
  - rosmaster
  - m3 pro
  - sim-to-real
  - curriculum learning
  - ppo
  - sac
  - navigation
  - slam
  - shml-robotics
---

# Robotics Sim Skill

## Target Hardware

**ROSMASTER M3 PRO** (Yahboom) — mecanum-wheel ground robot with:
- Jetson Orin / Xavier / Nano compute options
- ROS2 Jazzy / Humble support
- LIDAR, depth camera, ultrasonic sensors
- Supports Nav2, SLAM, manipulation via arm attachment

## Platform Context

- **GitLab project**: `shml/robotics` (ID=3, `~/Projects/shml-robotics`)
- **Phases**: 0 (Platform Gate) → 1 (Sim Foundation) → 2 (RL Training) → 3 (Isaac Sim) → 4 (AutoResearch) → 5 (Hardware Deploy)
- **Current status**: Phase 0 issues in `status::ready`. Phase 1 issues in `status::backlog`.
- **GitLab UI**: `http://172.30.0.12:8929/gitlab/shml/robotics`

## Robotics Track Layout (planned)

```
shml-robotics/
├── .gitlab-ci.yml         — CI (build stage active, jobs TBD)
├── README.md              — Project description
├── ros2_ws/               — (Phase 1) ROS2 colcon workspace
│   └── src/
├── sim/
│   ├── mujoco/            — (Phase 1) MuJoCo Docker + Gymnasium envs
│   ├── isaac/             — (Phase 3) Isaac Sim NGC container
│   └── drone/             — (Track A) Crazyflow / gym-pybullet-drones
├── models/
│   └── m3_pro/            — URDF → MJCF → USD conversions
├── training/
│   ├── ppo_nav.py         — PPO navigation training (Ray job)
│   └── sac_grasp.py       — SAC grasping training (Ray job)
└── rewards/               — Shared reward functions
```

## Track A: Drone Proving Ground (GitLab issues #43-#47)

Drone sims validate the RL pipeline quickly before heavier M3 PRO work.

### Frameworks (ranked by recommendation)

1. **Crazyflow** (`pip install crazyflow`) — JAX, 100M steps/sec on GPU, differentiable
   - `from crazyflow.sim import Sim; env = Sim(n_worlds=1024, n_drones=1)`
   - Domain randomization built in; MuJoCo renderer for visualization

2. **gym-pybullet-drones** (`pip install gym-pybullet-drones`) — PyBullet, 1.9K stars
   - Gymnasium-compatible, works with SB3 PPO, Betaflight SITL support

3. **L2F/RLtools** (`pip install l2f`) — C++/CUDA core, 18s to train hover policy
   - Proven Crazyflie sim-to-real (10/10 seeds hover)

### Drone RL quick-start (Crazyflow)
```python
from crazyflow.sim import Sim
import jax.numpy as jnp

sim = Sim(n_worlds=512, n_drones=1, physics="so_rpy_rotor")
state = sim.reset()
# Train with PPO or SAC via Ray + MLflow
```

## Track B: MuJoCo/ROS2/URDF (main robotics track)

### Phase 1 Priority Issues
| Issue | Title | Component | Complexity |
|-------|-------|-----------|------------|
| #7 | ROS2 colcon workspace structure | ros2 | 0.25 |
| #8 | GitLab CI pipeline | infra | 0.20 |
| #9 | Robotics state files for GitLab sync | infra | 0.15 |
| #10 | MuJoCo Docker container | mujoco | 0.40 |
| #11 | ROSMASTER M3 PRO URDF → MJCF → USD | urdf | 0.45 |
| #12 | MuJoCo Gymnasium environments | mujoco | 0.50 |

### URDF → MJCF conversion pattern
```bash
# Yahboom provides official URDF for M3 PRO
# Convert chain: URDF → MJCF (mujoco's own tool) → USD (Isaac Sim)
python3 -c "import mujoco; mujoco.MjModel.from_xml_path('m3_pro.urdf')"
# Or use: ros2 pkg create --build-type ament_python m3_pro_description
```

### MuJoCo Gymnasium env pattern
```python
import gymnasium as gym
import mujoco

class M3ProNavEnv(gym.Env):
    def __init__(self):
        self.model = mujoco.MjModel.from_xml_path("m3_pro.xml")
        self.data = mujoco.MjData(self.model)
        # Observation: [x, y, yaw, lidar_12beam, ...] → 18-dim
        # Action: [left_vel, right_vel] → 2-dim (differential drive)
        self.observation_space = gym.spaces.Box(...)
        self.action_space = gym.spaces.Box(-1, 1, shape=(2,))
```

## GitLab Operations (project 3)

Always set `GITLAB_PROJECT_ID=3` before using `gitlab_utils.py` for robotics issues.

```bash
# From host (terminal)
export GITLAB_PROJECT_ID=3
export GITLAB_BASE_URL=http://172.30.0.12:8929/gitlab
python3 /home/axelofwar/Projects/shml-platform/scripts/platform/gitlab_utils.py list-issues --state opened

# Create a robotics issue
python3 /home/axelofwar/Projects/shml-platform/scripts/platform/gitlab_utils.py \
    create-issue "P1.3: Implement ROS2 workspace" \
    --labels "type::feature,component::ros2,priority::high,status::backlog"
```

```python
# From Python (in-process)
import os, sys
os.environ['GITLAB_PROJECT_ID'] = '3'
os.environ['GITLAB_BASE_URL'] = 'http://172.30.0.12:8929/gitlab'
sys.path.insert(0, '/home/axelofwar/Projects/shml-platform')
from scripts.platform.gitlab_utils import list_issues, create_issue, upsert_issue

issues = list_issues(state='opened')
```

## Agent Autonomy for Robotics Issues

### Can claim autonomously (complexity ≤ 0.4)
- Docs updates, README, research notes (0.10–0.15)
- GitLab CI pipeline skeleton (0.20)
- Robotics state files / JSON configs (0.15)
- ROS2 colcon workspace scaffold (0.25)
- Drone pipeline YAML definitions (0.20)
- Crazyflow Dockerfile (0.35)

### Human-gated (complexity > 0.4)
- MuJoCo Docker container + Gymnasium envs (0.40–0.50)
- URDF model conversion (0.45)
- Ray RL training scripts (0.50–0.60)
- Isaac Sim integration (0.70)
- Hardware deployment (0.80)

## Context Window Budget
- **≤5 files** → safe to claim
- **5–20 files** → claim with caution
- **>20 files** → break into sub-issues first
- **`type::training`** → route to Ray pipeline, never claim

## Key Labels (project 3)
```
component::mujoco       — MuJoCo headless RL sim
component::ros2         — ROS2 Jazzy/Humble
component::urdf         — Robot description / URDF / MJCF / USD
component::isaac-sim    — NVIDIA Isaac Sim
component::rl-training  — RL training (PPO/SAC/etc.)
component::world-model  — Dreamer V3 / world models
component::drone        — Drone/quadrotor simulation
component::crazyflie    — Crazyflie 2.x hardware
component::crazyflow    — JAX-based Crazyflow sim
component::autoresearch — AutoResearch loop
component::hardware     — ROSMASTER M3 PRO hardware
component::cosmos       — NVIDIA Cosmos foundation model
component::groot        — NVIDIA Groot manipulation
```
