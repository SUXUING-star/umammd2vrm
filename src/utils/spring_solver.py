import math

# 按空间朝向与部位定义物理运动学收敛目标（由 Verlet 仿真直接验证并收敛）
MOTION_TARGETS = {
    "bust": {
        "overshoot": (0.06, 0.13),
        "settle_time": (0.14, 0.26),
        "drag_range": (0.32, 0.46),
        "alpha_max": 0.68,
        "max_walk_deg": 7.0,
        "max_sway_deg": 8.0,
        "sag_deg": 1.5,
        "taper_k": 0.90,
        "taper_d": 1.05,
    },
    "bangs": {
        "overshoot": (0.08, 0.15),  # 前发：强支撑，不往脸上/脑后糊，微弹自然
        "settle_time": (0.16, 0.28),
        "drag_range": (0.30, 0.44),
        "alpha_max": 0.66,
        "max_walk_deg": 9.5,
        "max_sway_deg": 11.0,
        "sag_deg": 2.0,
        "taper_k": 0.86,
        "taper_d": 1.08,
    },
    "front_skirt": {
        "overshoot": (0.10, 0.18),  # 前裙摆：防向后贴大腿，被腿顶开后迅速弹回
        "settle_time": (0.20, 0.34),
        "drag_range": (0.28, 0.40),
        "alpha_max": 0.62,
        "max_walk_deg": 12.5,
        "max_sway_deg": 15.0,
        "sag_deg": 4.5,
        "taper_k": 0.82,
        "taper_d": 1.08,
    },
    "side_skirt": {
        "overshoot": (0.10, 0.18),
        "settle_time": (0.22, 0.36),
        "drag_range": (0.28, 0.40),
        "alpha_max": 0.58,
        "max_walk_deg": 16.0,
        "max_sway_deg": 18.5,
        "sag_deg": 5.0,
        "taper_k": 0.78,
        "taper_d": 1.10,
    },
    "skirt": {
        "overshoot": (0.12, 0.20),  # 后裙摆：更飘逸舒展
        "settle_time": (0.24, 0.40),
        "drag_range": (0.26, 0.38),
        "alpha_max": 0.55,
        "max_walk_deg": 21.5,
        "max_sway_deg": 22.0,
        "sag_deg": 5.5,
        "taper_k": 0.76,
        "taper_d": 1.12,
    },
    "sleeve": {
        "overshoot": (0.10, 0.18),  # 袖子：兼顾手臂快动防穿模与布料阻尼
        "settle_time": (0.22, 0.36),
        "drag_range": (0.28, 0.40),
        "alpha_max": 0.58,
        "max_walk_deg": 15.0,
        "max_sway_deg": 17.5,
        "sag_deg": 4.5,
        "taper_k": 0.80,
        "taper_d": 1.10,
    },
    "hair": {
        "overshoot": (0.14, 0.22),
        "settle_time": (0.28, 0.46),
        "drag_range": (0.26, 0.38),
        "alpha_max": 0.55,
        "max_walk_deg": 22.5,
        "max_sway_deg": 25.0,
        "sag_deg": 5.5,
        "taper_k": 0.72,
        "taper_d": 1.12,
    },
    "other": {
        "overshoot": (0.12, 0.20),
        "settle_time": (0.24, 0.40),
        "drag_range": (0.27, 0.40),
        "alpha_max": 0.58,
        "max_walk_deg": 20.0,
        "max_sway_deg": 22.0,
        "sag_deg": 4.5,
        "taper_k": 0.78,
        "taper_d": 1.10,
    },
}


def _v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _v_cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _v_len(a):
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _v_norm(a):
    l = _v_len(a)
    if l < 1e-12:
        return (0.0, 0.0, -1.0)
    inv = 1.0 / l
    return (a[0] * inv, a[1] * inv, a[2] * inv)


def _rotate_from_to(v, u_from, u_to):
    c = _v_dot(u_from, u_to)
    if c > 0.999999:
        return v
    if c < -0.999999:
        axis = _v_cross((1.0, 0.0, 0.0), u_from)
        if _v_len(axis) < 1e-4:
            axis = _v_cross((0.0, 1.0, 0.0), u_from)
        axis = _v_norm(axis)
        d2 = 2.0 * _v_dot(v, axis)
        return _v_sub(_v_mul(axis, d2), v)

    cx = _v_cross(u_from, u_to)
    w = 1.0 + c
    q_len = math.sqrt(w * w + cx[0] * cx[0] + cx[1] * cx[1] + cx[2] * cx[2])
    qw = w / q_len
    qv = (cx[0] / q_len, cx[1] / q_len, cx[2] / q_len)
    t = _v_mul(_v_cross(qv, v), 2.0)
    return _v_add(v, _v_add(_v_mul(t, qw), _v_cross(qv, t)))


def _rest_axis_for_part(part: str):
    if part == "bust":
        return _v_norm((0.0, -0.96, -0.28))
    return _v_norm((0.0, -0.22, -0.975))


def _simulate_verlet_chain(
    seg_lens,
    params,
    rest_dir,
    dt,
    steps,
    root_pos_fn,
    init_deflect_dir=None,
    init_angle_rad=0.0,
    gravity_enabled=True,
):
    """严格复现 VRMC_springBone-1.0 运行时多关节 Verlet 动力学积分。"""
    m = len(seg_lens)
    grav_dir = (0.0, 0.0, -1.0)

    r0 = root_pos_fn(0.0)
    if init_angle_rad > 1e-6 and init_deflect_dir is not None:
        ca = math.cos(init_angle_rad)
        sa = math.sin(init_angle_rad)
        d_init = _v_norm(_v_add(_v_mul(rest_dir, ca), _v_mul(init_deflect_dir, sa)))
    else:
        d_init = rest_dir

    curr_tails = []
    prev_tails = []
    h = r0
    for l_i in seg_lens:
        t = _v_add(h, _v_mul(d_init, l_i))
        curr_tails.append(t)
        prev_tails.append(t)
        h = t

    tip_vecs = []
    for step in range(1, steps + 1):
        t_now = step * dt
        h = root_pos_fn(t_now)
        parent_from = rest_dir
        parent_to = rest_dir

        for i in range(m):
            k_i, d_i, g_i = params[i]
            l_i = seg_lens[i]
            local_rest = (
                rest_dir
                if i == 0
                else _rotate_from_to(rest_dir, parent_from, parent_to)
            )
            inertia = _v_mul(_v_sub(curr_tails[i], prev_tails[i]), 1.0 - d_i)
            stiff_vec = _v_mul(local_rest, dt * k_i)
            ext_vec = _v_mul(grav_dir, dt * g_i) if gravity_enabled else (0.0, 0.0, 0.0)
            nxt = _v_add(curr_tails[i], _v_add(inertia, _v_add(stiff_vec, ext_vec)))
            dir_now = _v_norm(_v_sub(nxt, h))
            nxt_constrained = _v_add(h, _v_mul(dir_now, l_i))

            prev_tails[i] = curr_tails[i]
            curr_tails[i] = nxt_constrained
            parent_from = rest_dir
            parent_to = dir_now
            h = nxt_constrained

        tip_vecs.append(_v_sub(curr_tails[-1], root_pos_fn(t_now)))
    return tip_vecs


def _signed_angle_in_plane(vec, rest_dir, perp_dir):
    return math.atan2(_v_dot(vec, perp_dir), _v_dot(vec, rest_dir))


def _evaluate_chain_motion(part, seg_lens, params):
    rest_dir = _rest_axis_for_part(part)
    lat_dir = (1.0, 0.0, 0.0)
    sag_perp = _v_norm(_v_cross(lat_dir, rest_dir))

    theta_0 = math.radians(20.0)
    dt60 = 1.0 / 60.0
    vecs_rel = _simulate_verlet_chain(
        seg_lens,
        params,
        rest_dir,
        dt60,
        steps=54,
        root_pos_fn=lambda t: (0.0, 0.0, 0.0),
        init_deflect_dir=lat_dir,
        init_angle_rad=theta_0,
        gravity_enabled=False,
    )
    angles60 = [_signed_angle_in_plane(v, rest_dir, lat_dir) for v in vecs_rel]
    min_ang = min(angles60)
    overshoot = max(0.0, -min_ang) / theta_0

    thresh = 0.05 * theta_0
    last_over = -1
    for idx, a in enumerate(angles60):
        if abs(a) > thresh:
            last_over = idx
    settle_time = (last_over + 1) * dt60 if last_over >= 0 else 0.0

    dt30 = 1.0 / 30.0
    vecs_30 = _simulate_verlet_chain(
        seg_lens,
        params,
        rest_dir,
        dt30,
        steps=20,
        root_pos_fn=lambda t: (0.0, 0.0, 0.0),
        init_deflect_dir=lat_dir,
        init_angle_rad=theta_0,
        gravity_enabled=False,
    )
    angles30 = [_signed_angle_in_plane(v, rest_dir, lat_dir) for v in vecs_30]
    sign_flips = sum(
        1 for i in range(1, len(angles30)) if angles30[i] * angles30[i - 1] < 0.0
    )
    stable_30fps = (
        max(abs(a) for a in angles30[2:]) <= 1.05 * theta_0
        and abs(angles30[-1]) <= 0.60 * theta_0
        and not (
            sign_flips >= len(angles30) - 3
            and max(abs(a) for a in angles30[6:]) > 0.15 * theta_0
        )
    )

    v_walk = 1.0
    vecs_walk = _simulate_verlet_chain(
        seg_lens,
        params,
        rest_dir,
        dt60,
        steps=36,
        root_pos_fn=lambda t: (
            0.0,
            -v_walk * min(t, 0.6) * (min(t, 0.15) / 0.15 if t < 0.15 else 1.0),
            0.0,
        ),
        gravity_enabled=True,
    )
    vecs_rest = _simulate_verlet_chain(
        seg_lens,
        params,
        rest_dir,
        dt60,
        steps=30,
        root_pos_fn=lambda t: (0.0, 0.0, 0.0),
        gravity_enabled=True,
    )
    rest_eq = _v_norm(vecs_rest[-1])
    walk_deg = max(
        math.degrees(math.acos(max(-1.0, min(1.0, _v_dot(_v_norm(v), rest_eq)))))
        for v in vecs_walk[-12:]
    )

    freq_sway = 1.8
    amp_sway = 0.45 / (2.0 * math.pi * freq_sway)
    vecs_sway = _simulate_verlet_chain(
        seg_lens,
        params,
        rest_dir,
        dt60,
        steps=54,
        root_pos_fn=lambda t: (
            amp_sway * math.sin(2.0 * math.pi * freq_sway * t),
            0.0,
            0.0,
        ),
        gravity_enabled=True,
    )
    sway_peak_deg = max(
        abs(math.degrees(_signed_angle_in_plane(v, rest_dir, lat_dir)))
        for v in vecs_sway[6:]
    )

    sag_deg = abs(math.degrees(_signed_angle_in_plane(rest_eq, rest_dir, sag_perp)))

    return {
        "overshoot": overshoot,
        "settle_time": settle_time,
        "walk_deg": walk_deg,
        "sway_deg": sway_peak_deg,
        "sag_deg": sag_deg,
        "stable_30fps": stable_30fps,
    }


def _build_chain_params(seg_lens, alpha_base, d_base, g_base, target, sp_norm, k_cap):
    m = len(seg_lens)
    denom = max(1, m - 1)
    sp_boost = 0.92 + 0.16 * sp_norm
    d_min, d_max = target["drag_range"]
    out = []
    for i, l_i in enumerate(seg_lens):
        t = i / denom if m > 1 else 0.0
        k_scale = (1.0 - (1.0 - target["taper_k"]) * t) * sp_boost
        d_scale = 1.0 + (target["taper_d"] - 1.0) * t
        k_i = min(k_cap, max(0.05, alpha_base * 60.0 * l_i * k_scale))
        d_i = min(d_max, max(d_min, d_base * d_scale))
        g_i = max(0.0, min(0.35, g_base * max(0.35, min(1.3, l_i / 0.08))))
        out.append((k_i, d_i, g_i))
    return out


_SOLVER_CACHE = {}


def solve_chain_spring_params(part: str, seg_lens, sp_norm=0.35, k_cap=6.0):
    """通过多关节 Verlet 运动解算使参数收敛到目标运动指标。"""
    seg_lens = [max(0.01, float(l)) for l in seg_lens] or [0.05]
    part_key = part if part in MOTION_TARGETS else "other"
    cache_key = (
        part_key,
        tuple(round(l, 3) for l in seg_lens),
        round(float(sp_norm), 2),
    )
    if cache_key in _SOLVER_CACHE:
        return _SOLVER_CACHE[cache_key]

    tgt = MOTION_TARGETS[part_key]
    mp_min, mp_max = tgt["overshoot"]
    t95_min, t95_max = tgt["settle_time"]
    d_min, d_max = tgt["drag_range"]
    alpha_hi = tgt["alpha_max"]
    mp_mid = 0.5 * (mp_min + mp_max)
    t95_mid = 0.5 * (t95_min + t95_max)

    ln_mp = math.log(max(0.02, mp_mid))
    zeta = -ln_mp / math.sqrt(math.pi * math.pi + ln_mp * ln_mp)
    zeta = max(0.20, min(0.85, zeta))
    omega_n = 3.0 / max(0.05, zeta * t95_mid)
    dt = 1.0 / 60.0

    d_base = max(d_min, min(d_max, 1.0 - math.exp(-2.0 * zeta * omega_n * dt)))
    cos_arg = omega_n * math.sqrt(max(0.01, 1.0 - zeta * zeta)) * dt
    alpha_base = max(
        0.12,
        min(
            alpha_hi,
            2.0 - d_base - 2.0 * math.sqrt(max(0.01, 1.0 - d_base)) * math.cos(cos_arg),
        ),
    )
    g_base = 0.02 if part_key == "bust" else 0.10

    best_score = float("inf")
    best_pair = (alpha_base, d_base)

    for _ in range(22):
        params = _build_chain_params(
            seg_lens, alpha_base, d_base, g_base, tgt, sp_norm, k_cap
        )
        m = _evaluate_chain_motion(part_key, seg_lens, params)

        stab_pen = 0.0 if m["stable_30fps"] else 1000.0
        walk_pen = max(0.0, m["walk_deg"] - tgt["max_walk_deg"]) * 8.0
        sway_pen = max(0.0, m["sway_deg"] - tgt["max_sway_deg"]) * 12.0
        mp_pen = (
            max(0.0, mp_min - m["overshoot"]) * 45.0
            + max(0.0, m["overshoot"] - mp_max) * 45.0
            + abs(m["overshoot"] - mp_mid) * 6.0
        )
        t95_pen = (
            max(0.0, t95_min - m["settle_time"]) * 25.0
            + max(0.0, m["settle_time"] - t95_max) * 25.0
            + abs(m["settle_time"] - t95_mid) * 3.0
        )
        score = stab_pen + walk_pen + sway_pen + mp_pen + t95_pen

        if score < best_score:
            best_score = score
            best_pair = (alpha_base, d_base)

        if (
            m["stable_30fps"]
            and m["walk_deg"] <= tgt["max_walk_deg"]
            and m["sway_deg"] <= tgt["max_sway_deg"]
            and mp_min <= m["overshoot"] <= mp_max
            and t95_min <= m["settle_time"] <= t95_max
        ):
            break

        if not m["stable_30fps"]:
            alpha_hi = min(alpha_hi, alpha_base * 0.90)
            alpha_base = max(0.08, alpha_base * 0.82)
            d_base = min(d_max, d_base + 0.04)
            continue

        over_motion = (
            m["walk_deg"] > tgt["max_walk_deg"] or m["sway_deg"] > tgt["max_sway_deg"]
        )
        if over_motion:
            ratio = max(
                m["walk_deg"] / max(1.0, tgt["max_walk_deg"]),
                m["sway_deg"] / max(1.0, tgt["max_sway_deg"]),
            )
            if alpha_base < alpha_hi * 0.97:
                alpha_base = min(alpha_hi, alpha_base * min(1.35, 0.85 + 0.30 * ratio))
            elif m["overshoot"] < mp_max:
                d_base = max(d_min, d_base - 0.04)
            if m["overshoot"] > mp_max:
                d_base = min(d_max, d_base + 0.03)
        else:
            if m["overshoot"] > mp_max:
                d_base = min(
                    d_max, d_base + min(0.07, 0.35 * (m["overshoot"] - mp_mid))
                )
            elif m["overshoot"] < mp_min:
                d_base = max(
                    d_min, d_base - min(0.07, 0.35 * (mp_mid - m["overshoot"]))
                )

            if m["settle_time"] > t95_max:
                alpha_base = min(alpha_hi, alpha_base * 1.12)
                d_base = min(d_max, d_base + 0.02)
            elif (
                m["settle_time"] < t95_min
                and m["sway_deg"] < tgt["max_sway_deg"] * 0.85
            ):
                alpha_base = max(0.10, alpha_base * 0.90)

    alpha_opt, d_opt = best_pair

    g_lo, g_hi = 0.0, 0.35
    g_opt = g_base
    target_sag = tgt["sag_deg"]
    for _ in range(7):
        g_mid = 0.5 * (g_lo + g_hi)
        p_test = _build_chain_params(
            seg_lens, alpha_opt, d_opt, g_mid, tgt, sp_norm, k_cap
        )
        rest_dir = _rest_axis_for_part(part_key)
        lat_dir = (1.0, 0.0, 0.0)
        sag_perp = _v_norm(_v_cross(lat_dir, rest_dir))
        vecs_eq = _simulate_verlet_chain(
            seg_lens,
            p_test,
            rest_dir,
            dt,
            steps=30,
            root_pos_fn=lambda t: (0.0, 0.0, 0.0),
            gravity_enabled=True,
        )
        sag_now = abs(
            math.degrees(_signed_angle_in_plane(vecs_eq[-1], rest_dir, sag_perp))
        )
        g_opt = g_mid
        if abs(sag_now - target_sag) < 0.25:
            break
        if sag_now < target_sag:
            g_lo = g_mid
        else:
            g_hi = g_mid

    final_params = _build_chain_params(
        seg_lens, alpha_opt, d_opt, g_opt, tgt, sp_norm, k_cap
    )
    final_metrics = _evaluate_chain_motion(part_key, seg_lens, final_params)
    joint_params = list(final_params) + [final_params[-1]]

    res = (joint_params, final_metrics)
    _SOLVER_CACHE[cache_key] = res
    return res
