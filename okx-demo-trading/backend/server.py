"""
OKX 模拟交易后端 API 服务
Flask REST API，对接 OKX Demo Trading
"""

import os
import json
from flask import Flask, request, jsonify, send_from_directory, redirect
from flask_cors import CORS
from okx_client import OKXDemoClient

# 前端目录（相对于本文件）
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)

# 初始化客户端（从环境变量读取）
client = OKXDemoClient(
    api_key=os.environ.get("OKX_API_KEY", ""),
    secret_key=os.environ.get("OKX_SECRET_KEY", ""),
    passphrase=os.environ.get("OKX_PASSPHRASE", ""),
)


def ok_response(data):
    return jsonify({"code": 0, "data": data})


def err_response(msg, code=1):
    return jsonify({"code": code, "msg": msg}), 400


# ==================== 行情接口 ====================

@app.route("/api/tickers")
def get_tickers():
    """获取合约行情列表"""
    inst_type = request.args.get("instType", "SWAP")
    result = client.get_tickers(inst_type)
    return jsonify(result)


@app.route("/api/ticker")
def get_ticker():
    """获取单个产品行情"""
    inst_id = request.args.get("instId", "BTC-USDT-SWAP")
    result = client.get_ticker(inst_id)
    return jsonify(result)


@app.route("/api/candles")
def get_candles():
    """获取K线"""
    inst_id = request.args.get("instId", "BTC-USDT-SWAP")
    bar = request.args.get("bar", "15m")
    limit = request.args.get("limit", "100")
    result = client.get_candles(inst_id, bar, int(limit))
    return jsonify(result)


@app.route("/api/orderbook")
def get_orderbook():
    """获取订单簿"""
    inst_id = request.args.get("instId", "BTC-USDT-SWAP")
    sz = request.args.get("sz", "20")
    result = client.get_orderbook(inst_id, int(sz))
    return jsonify(result)


# ==================== 账户接口 ====================

@app.route("/api/balance")
def get_balance():
    """获取余额"""
    result = client.get_balance()
    return jsonify(result)


@app.route("/api/positions")
def get_positions():
    """获取持仓"""
    inst_type = request.args.get("instType", "SWAP")
    result = client.get_positions(inst_type)
    return jsonify(result)


@app.route("/api/account-config")
def get_account_config():
    """获取账户配置"""
    result = client.get_account_config()
    return jsonify(result)


@app.route("/api/set-leverage", methods=["POST"])
def set_leverage():
    """设置杠杆"""
    body = request.get_json()
    inst_id = body.get("instId", "")
    lever = body.get("lever", 10)
    mgn_mode = body.get("mgnMode", "cross")
    if not inst_id:
        return err_response("缺少 instId")
    result = client.set_leverage(inst_id, lever, mgn_mode)
    return jsonify(result)


# ==================== 交易接口 ====================

@app.route("/api/order", methods=["POST"])
def place_order():
    """下单"""
    body = request.get_json()
    required = ["instId", "tdMode", "side", "ordType", "sz"]
    for field in required:
        if field not in body:
            return err_response(f"缺少参数: {field}")

    result = client.place_order(
        inst_id=body["instId"],
        td_mode=body["tdMode"],
        side=body["side"],
        ord_type=body["ordType"],
        sz=body["sz"],
        px=body.get("px", ""),
        pos_side=body.get("posSide", "net"),
        tp_trigger_px=body.get("tpTriggerPx", ""),
        tp_ord_px=body.get("tpOrdPx", ""),
        sl_trigger_px=body.get("slTriggerPx", ""),
        sl_ord_px=body.get("slOrdPx", ""),
    )
    return jsonify(result)


@app.route("/api/cancel-order", methods=["POST"])
def cancel_order():
    """撤单"""
    body = request.get_json()
    inst_id = body.get("instId", "")
    ord_id = body.get("ordId", "")
    cl_ord_id = body.get("clOrdId", "")
    if not inst_id:
        return err_response("缺少 instId")
    if not ord_id and not cl_ord_id:
        return err_response("需要 ordId 或 clOrdId")
    result = client.cancel_order(inst_id, ord_id, cl_ord_id)
    return jsonify(result)


@app.route("/api/orders-pending")
def get_orders_pending():
    """挂单列表"""
    inst_type = request.args.get("instType", "SWAP")
    result = client.get_orders_pending(inst_type)
    return jsonify(result)


@app.route("/api/orders-history")
def get_orders_history():
    """历史订单"""
    inst_type = request.args.get("instType", "SWAP")
    limit = request.args.get("limit", "50")
    result = client.get_orders_history(inst_type, int(limit))
    return jsonify(result)


# ==================== 产品列表 ====================

@app.route("/api/instruments")
def get_instruments():
    """获取可交易合约列表"""
    inst_type = request.args.get("instType", "SWAP")
    result = client.get_instruments(inst_type)
    return jsonify(result)


# ==================== 前端面板 ====================

@app.route("/")
def root():
    return redirect("/panel")

@app.route("/panel")
def panel():
    return send_from_directory(FRONTEND_DIR, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8899))
    print(f"\n  🚀 OKX 模拟合约交易已启动")
    print(f"  📊 交易面板: http://localhost:{port}/panel")
    print(f"  📡 API 地址: http://localhost:{port}/api")
    print(f"\n  按 Ctrl+C 停止服务\n")
    app.run(host="0.0.0.0", port=port, debug=False)
