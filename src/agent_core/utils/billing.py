"""
LLM 计费工具

根据 token 用量和模型单价计算费用（人民币元）。
支持阶梯计费（按单次请求的输入 token 数分档）。
参考：https://help.aliyun.com/zh/model-studio/model-pricing
"""

from typing import Dict, List, Optional, Tuple

# 阶梯定义：(输入token上限, 输入单价, 输出单价) 元/百万token，中国内地
# 按单次请求的输入 Token 数分档
_TIERED_PRICES: Dict[str, List[Tuple[int, float, float]]] = {
    "qwen3.5-plus": [
        (128_000, 0.8, 4.8),  # 0 < input ≤ 128K
        (256_000, 2.0, 12.0),  # 128K < input ≤ 256K
        (1_000_000, 4.0, 24.0),  # 256K < input ≤ 1M
    ],
    "qwen-3.5-plus": [
        (128_000, 0.8, 4.8),
        (256_000, 2.0, 12.0),
        (1_000_000, 4.0, 24.0),
    ],
    "qwen3.5-plus-2026-02-15": [
        (128_000, 0.8, 4.8),
        (256_000, 2.0, 12.0),
        (1_000_000, 4.0, 24.0),
    ],
}

# 无阶梯模型：简单 (input_per_million, output_per_million)
_FLAT_PRICES: Dict[str, Tuple[float, float]] = {
    "qwen-turbo": (0.3, 0.6),
    "qwen-plus": (0.8, 2.0),  # qwen-plus 也有阶梯，此处用首档近似
    "qwen-max": (2.4, 9.6),
}


def _get_tier_prices(
    prompt_tokens: int, tiers: List[Tuple[int, float, float]]
) -> Tuple[float, float]:
    """根据单次请求的输入 token 数获取对应阶梯单价"""
    for limit, inp, out in tiers:
        if prompt_tokens <= limit:
            return (inp, out)
    # 超过最大阶梯，用最后一档
    return (tiers[-1][1], tiers[-1][2])


def _compute_cost_per_call(
    prompt_tokens: int, completion_tokens: int, model: str
) -> Optional[float]:
    """
    单次调用的阶梯计费。

    Args:
        prompt_tokens: 该次调用的输入 token 数
        completion_tokens: 该次调用的输出 token 数
        model: 模型名称

    Returns:
        该次调用的费用（元），未知模型返回 None
    """
    key = model if model in _TIERED_PRICES else model.lower().replace("_", "-")
    tiers = _TIERED_PRICES.get(key)
    if tiers:
        inp_p, out_p = _get_tier_prices(prompt_tokens, tiers)
        cost = (prompt_tokens / 1_000_000 * inp_p) + (
            completion_tokens / 1_000_000 * out_p
        )
        return round(cost, 6)

    # 无阶梯模型
    prices = _FLAT_PRICES.get(key) or _FLAT_PRICES.get(model.lower().replace("_", "-"))
    if prices is None:
        return None
    inp_p, out_p = prices
    cost = (prompt_tokens / 1_000_000 * inp_p) + (completion_tokens / 1_000_000 * out_p)
    return round(cost, 6)


def compute_cost(
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
) -> Optional[float]:
    """
    计算单次调用的费用（元），支持阶梯计费。

    Args:
        prompt_tokens: 输入 token 数
        completion_tokens: 输出 token 数
        model: 模型名称（如 qwen3.5-plus）

    Returns:
        费用（人民币元），未知模型返回 None
    """
    return _compute_cost_per_call(prompt_tokens, completion_tokens, model)


def compute_cost_from_calls(
    calls: List[Tuple[int, int]],
    model: str,
) -> Optional[float]:
    """
    根据多次调用的 (prompt_tokens, completion_tokens) 列表，按阶梯计费累加总费用。

    Args:
        calls: [(prompt_tokens, completion_tokens), ...]
        model: 模型名称

    Returns:
        总费用（元），未知模型返回 None
    """
    total = 0.0
    for pt, ct in calls:
        c = _compute_cost_per_call(pt, ct, model)
        if c is None:
            return None
        total += c
    return round(total, 6)


def get_model_prices(model: str) -> Optional[object]:
    """
    获取模型定价信息（阶梯或单价）。

    Returns:
        阶梯模型返回 tiers 列表，平价为 (input, output)，未知返回 None
    """
    key = model if model in _TIERED_PRICES else model.lower().replace("_", "-")
    if key in _TIERED_PRICES:
        return _TIERED_PRICES[key]
    if key in _FLAT_PRICES:
        return _FLAT_PRICES[key]
    return None
