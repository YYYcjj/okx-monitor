"""
OKX Demo Trading API Client
Supports simulated trading via x-simulated-trading: 1 header
"""

import hmac
import base64
import json
import time
from datetime import datetime
from urllib.parse import urlencode
import requests


class OKXDemoClient:
    """OKX 模拟交易客户端"""

    BASE_URL = "https://www.okx.com"

    def __init__(self, api_key: str, secret_key: str, passphrase: str):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """生成 OKX API 签名"""
        message = timestamp + method + path + body
        mac = hmac.new(
            self.secret_key.encode("utf-8"),
            message.encode("utf-8"),
            digestmod="sha256",
        )
        return base64.b64encode(mac.digest()).decode("utf-8")

    def _request(self, method: str, path: str, params: dict = None, data: dict = None) -> dict:
        """发送带签名的请求（模拟交易模式）"""
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        body = json.dumps(data) if data else ""

        # 处理 query string
        url_path = path
        if params:
            url_path = path + "?" + urlencode(params)

        sign = self._sign(timestamp, method, url_path, body)

        headers = {
            "Content-Type": "application/json",
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "x-simulated-trading": "1",  # 模拟交易关键头
        }

        url = self.BASE_URL + url_path

        if method == "GET":
            resp = requests.get(url, headers=headers, timeout=15)
        elif method == "POST":
            resp = requests.post(url, headers=headers, data=body, timeout=15)
        else:
            raise ValueError(f"Unsupported method: {method}")

        result = resp.json()
        if result.get("code") != "0":
            return {"error": True, "code": result.get("code"), "msg": result.get("msg", "Unknown error"), "data": result.get("data")}
        return {"error": False, "data": result.get("data", [])}

    # ==================== 行情数据 ====================

    def get_ticker(self, inst_id: str) -> dict:
        """获取单个产品行情"""
        return self._request("GET", "/api/v5/market/ticker", params={"instId": inst_id})

    def get_tickers(self, inst_type: str = "SWAP") -> dict:
        """批量获取行情"""
        return self._request("GET", "/api/v5/market/tickers", params={"instType": inst_type})

    def get_candles(self, inst_id: str, bar: str = "15m", limit: int = 100) -> dict:
        """获取K线数据"""
        return self._request("GET", "/api/v5/market/candles", params={
            "instId": inst_id, "bar": bar, "limit": str(limit)
        })

    def get_orderbook(self, inst_id: str, sz: int = 20) -> dict:
        """获取订单簿"""
        return self._request("GET", "/api/v5/market/books", params={"instId": inst_id, "sz": str(sz)})

    # ==================== 账户 ====================

    def get_balance(self) -> dict:
        """获取账户余额"""
        return self._request("GET", "/api/v5/account/balance")

    def get_positions(self, inst_type: str = "SWAP") -> dict:
        """获取持仓"""
        return self._request("GET", "/api/v5/account/positions", params={"instType": inst_type})

    def get_account_config(self) -> dict:
        """获取账户配置（杠杆、持仓模式等）"""
        return self._request("GET", "/api/v5/account/config")

    def set_leverage(self, inst_id: str, lever: int, mgn_mode: str = "cross") -> dict:
        """设置杠杆倍数"""
        return self._request("POST", "/api/v5/account/set-leverage", data={
            "instId": inst_id, "lever": str(lever), "mgnMode": mgn_mode
        })

    # ==================== 交易 ====================

    def place_order(self, inst_id: str, td_mode: str, side: str, ord_type: str,
                    sz: str, px: str = "", pos_side: str = "net",
                    tp_trigger_px: str = "", tp_ord_px: str = "",
                    sl_trigger_px: str = "", sl_ord_px: str = "") -> dict:
        """下单（支持止盈止损）"""
        data = {
            "instId": inst_id,
            "tdMode": td_mode,  # cross / isolated
            "side": side,       # buy / sell
            "ordType": ord_type, # market / limit
            "sz": sz,
            "posSide": pos_side, # long / short / net
        }
        if px:
            data["px"] = px
        # 止盈止损
        if tp_trigger_px and tp_ord_px:
            data["tpTriggerPx"] = tp_trigger_px
            data["tpOrdPx"] = tp_ord_px
        if sl_trigger_px and sl_ord_px:
            data["slTriggerPx"] = sl_trigger_px
            data["slOrdPx"] = sl_ord_px

        return self._request("POST", "/api/v5/trade/order", data=data)

    def cancel_order(self, inst_id: str, ord_id: str = "", cl_ord_id: str = "") -> dict:
        """撤销订单"""
        data = {"instId": inst_id}
        if ord_id:
            data["ordId"] = ord_id
        if cl_ord_id:
            data["clOrdId"] = cl_ord_id
        return self._request("POST", "/api/v5/trade/cancel-order", data=data)

    def get_order(self, inst_id: str, ord_id: str = "", cl_ord_id: str = "") -> dict:
        """查询订单详情"""
        params = {"instId": inst_id}
        if ord_id:
            params["ordId"] = ord_id
        if cl_ord_id:
            params["clOrdId"] = cl_ord_id
        return self._request("GET", "/api/v5/trade/order", params=params)

    def get_orders_pending(self, inst_type: str = "SWAP") -> dict:
        """获取挂单列表"""
        return self._request("GET", "/api/v5/trade/orders-pending", params={"instType": inst_type})

    def get_orders_history(self, inst_type: str = "SWAP", limit: int = 50) -> dict:
        """获取历史订单"""
        return self._request("GET", "/api/v5/trade/orders-history", params={
            "instType": inst_type, "limit": str(limit)
        })

    # ==================== 公共数据 ====================

    def get_instruments(self, inst_type: str = "SWAP") -> dict:
        """获取可交易产品列表"""
        return self._request("GET", "/api/v5/public/instruments", params={"instType": inst_type})
