import os
import websockets
try: from .launchlab import (
    LAUNCHPAD_POOL_LAYOUT,
    RaydiumLaunchpadCore,
    RaydiumLaunchpadSwap,
)
except: from launchlab import (
    LAUNCHPAD_POOL_LAYOUT,
    RaydiumLaunchpadCore,
    RaydiumLaunchpadSwap,
)
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solana.rpc.commitment import Processed, Confirmed
from dotenv import load_dotenv
import asyncio
import json
import base64
import time
import logging
import traceback, sys
try: from .colors import  *
except: from colors import  *
import aiohttp
from collections import defaultdict
from pathlib import Path

load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)

WSOL_MINT = Pubkey.from_string("So11111111111111111111111111111111111111112")
SOL_LAMPORT_PER_TOKEN = 1e9

HTTP_RPC = os.getenv("HTTP_RPC")
WS_RPC_URL = os.getenv("WS_RPC_URL")
KEYPAIR = os.getenv("KEYPAIR")
BUY_AMOUNT = float(os.getenv("BUY_AMOUNT"))
FEE = float(os.getenv("FEE"))
MIN_BUYS = int(os.getenv("MIN_BUYS"))
FROM_OPEN = float(os.getenv("FROM_OPEN"))
SLIPPAGE_PCT = int(os.getenv("SLIPPAGE_PCT"))
ENTER_LOW_PRICE = bool(os.getenv("ENTER_LOW_PRICE"))
MAX_LOSS_FROM_HIGH = int(os.getenv("MAX_LOSS_FROM_HIGH"))
MAX_INACTIVITY_TIME = int(os.getenv("MAX_INACTIVITY_TIME"))
MAX_LOSS = int(os.getenv("MAX_LOSS"))
TARGET_PROFIT = float(os.getenv("TARGET_PROFIT"))
DEBUG_ = bool(os.getenv("DEBUG_"))

for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

suppress_logs = [
    "socks",
    "requests",
    "httpx",    
    "trio.async_generator_errors",
    "trio",
    "trio.abc.Instrument",
    "trio.abc",
    "trio.serve_listeners",
    "httpcore.http11",
    "httpcore",
    "httpcore.connection",
    "httpcore.proxy",
]

for log_name in suppress_logs:
    logging.getLogger(log_name).setLevel(logging.CRITICAL)
    logging.getLogger(log_name).handlers.clear()
    logging.getLogger(log_name).propagate = False

logging.basicConfig(
    level=logging.INFO,
    format=f'%(asctime)s {cc.AQUA}☆ X-Ray ☆ {cc.LIGHT_GRAY}┃{cc.RESET} {cc.LIGHT_WHITE}%(message)s{cc.RESET}',
    datefmt='%H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True
)

class XRay:
    def __init__(self):
        self.client = AsyncClient(HTTP_RPC)
        self.keypair = Keypair.from_base58_string(KEYPAIR)
        self.launchpad_core = RaydiumLaunchpadCore(self.client)
        self.launchpad_swap = RaydiumLaunchpadSwap(self.keypair, self.client)
        self.accounts = set()
        self.updates = asyncio.Queue()
        self.stop_event = asyncio.Event()
        self.logs = asyncio.Queue()
        self.session = aiohttp.ClientSession()
        self.mint_queue = asyncio.Queue()
        self.mint_data = defaultdict(lambda: {
            "current_price": 0.0,
            "open_price": 0.0,
            "low_price": 0.0000000280,
            "high_price": 0.0,
            "stats": {
                "buys": 0,
                "sells": 0,
                }
            }
        )
        self.holdings = set()
        self.sold = set()

    async def buy(self, mint: str, pool_id: str):
        if mint not in self.holdings:
            self.holdings.add(mint)
            lams = int(BUY_AMOUNT * SOL_LAMPORT_PER_TOKEN)
            ok, sig = await self.launchpad_swap.execute_lp_buy_async(
                token_mint=mint,
                pool_id=pool_id,
                sol_lamports=lams,
                slippage_pct=SLIPPAGE_PCT,
                fee_micro_lamports=int(FEE * SOL_LAMPORT_PER_TOKEN),
            )
            if ok:
                logging.info(f"{cc.LIGHT_GREEN}Bought {mint} for {BUY_AMOUNT} SOL | {sig} ✔")
            else:
                logging.info(f"{cc.RED}Failed to buy {mint} | {sig} ✘")

    async def sell(self, mint: str, pool_id: str):
        if mint in self.holdings:
            self.holdings.remove(mint)
            self.sold.add(mint)
            ok, sig = await self.launchpad_swap.execute_lp_sell_async(
                token_mint=mint,
                pool_id=pool_id,
                fee_micro_lamports=int(FEE * SOL_LAMPORT_PER_TOKEN),
                slippage_pct=SLIPPAGE_PCT,
            )
            if ok:
                logging.info(f"{cc.LIGHT_GREEN}Sold {mint} | {sig} ✔")
            else:
                logging.info(f"{cc.RED}Failed to sell {mint} | {sig} ✘")

    async def subscribe(self, program):
        """
            Subscribe to the Solana network for program logs. ~reusable, by FLOCK4H
        """
        while not self.stop_event.is_set():
            ws = None
            try:
                async with websockets.connect(WS_RPC_URL, ping_interval=2, ping_timeout=15) as ws:
                    await ws.send(json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "logsSubscribe",
                            "id": 1,
                            "params": [
                                {"mentions": [str(program)]},
                                {"commitment": "processed"}
                            ]
                        }))
                    response = json.loads(await ws.recv())

                    if 'result' in response:
                        logging.info(f"Successfully connected to {program} ✔")

                    async for message in ws:
                        if self.stop_event.is_set():
                            break
                        hMessage = json.loads(message)
                        await self.logs.put([hMessage, program])

            except websockets.exceptions.ConnectionClosedError:
                logging.error(f"Connection closed when subscribing to {program}")
                await asyncio.sleep(5)
            except TimeoutError:
                logging.error(f"TimeoutError when subscribing to {program}")
                await asyncio.sleep(5)
            except Exception as e:
                logging.error(f"Error when subscribing to {program}, {e}")
                await asyncio.sleep(5)
                traceback.print_exc()
            finally:
                if ws:
                    try:
                        await ws.close()
                    except RuntimeError:
                        break
                await asyncio.sleep(0.2)

    async def subscribe_state(self, pool_key: str, mint: str | Pubkey):
        """
        Stream updates from the Virtual-Pool account. ~reusable, by FLOCK4H
        """
        mint = mint if isinstance(mint, str) else str(mint)
        while mint not in self.sold:
            try:
                if mint not in self.accounts:
                    self.accounts.add(mint)
                else:
                    logging.info(f"Already subscribed to {mint}")
                    return

                async with websockets.connect(WS_RPC_URL, ping_interval=2, ping_timeout=15) as ws:
                    await ws.send(json.dumps({
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "accountSubscribe",
                        "params": [pool_key, {"encoding": "base64", "commitment": Processed}]
                    }))
                    await ws.recv()
                    logging.info(f"{cc.LIGHT_MAGENTA}Started price monitoring for {cc.BG_ORANGE}{mint}{cc.RESET} ✔")

                    async for raw in ws:
                        if mint in self.sold:
                            break
                        data_b64 = json.loads(raw)["params"]["result"]["value"]["data"][0]
                        blob     = base64.b64decode(data_b64) # 8-byte discr.
                        vp       = LAUNCHPAD_POOL_LAYOUT.parse(blob)
                        price    = self.calculate_price(vp)
                        await self.updates.put(
                            {"mint": mint, "price": price, "ts": time.time()}
                        )

            except (websockets.exceptions.ConnectionClosedError, asyncio.TimeoutError):
                await asyncio.sleep(3)            # quick back-off reconnect
            except Exception as err:
                logging.error(f"state-stream error {err}")
                traceback.print_exc()
                await asyncio.sleep(3)

    def calculate_price(self, keys) -> float:
        """
            Constant Product
        """
        virtual_a_decimal = keys.virtual_a / (10 ** keys.dec_a)
        virtual_b_decimal = keys.virtual_b / (10 ** keys.dec_b)
        real_a_decimal = keys.real_a / (10 ** keys.dec_a)
        real_b_decimal = keys.real_b / (10 ** keys.dec_b)
        
        # Price = (virtualB + realB) / (virtualA - realA)
        numerator = virtual_b_decimal + real_b_decimal
        denominator = virtual_a_decimal - real_a_decimal
        if denominator <= 0:
            return 0.0
        return (numerator / denominator)          

    def dig_logs(self, logs, sig):
        """
            Checks for InitializeMint, and returns signature of the tx
        """
        if sig is None:
            raise Exception("Signature is None")
        
        for log in logs:
            if "InitializeMint" in log:
                return sig
        return None

    async def process_updates(self):
        try:
            while True:
                update = await self.updates.get()
                mint = update['mint']
                price = update['price']
                if DEBUG_:
                    logging.info(f"{cc.LIGHT_MAGENTA}Update: {mint} | Price: {price:.10f}")

                if self.mint_data[mint]['open_price'] == 0.0:
                    self.mint_data[mint]['open_price'] = price

                if price > self.mint_data[mint]['current_price']:
                    self.mint_data[mint]['stats']['buys'] += 1
                elif price < self.mint_data[mint]['current_price']:
                    self.mint_data[mint]['stats']['sells'] += 1

                self.mint_data[mint]['current_price'] = price
                if self.mint_data[mint]['high_price'] < price:
                    self.mint_data[mint]['high_price'] = price
        except asyncio.CancelledError:
            return
        except Exception as e:
            logging.error(f"Error processing updates: {e}")
            traceback.print_exc()
            await asyncio.sleep(3)

    async def process_mint(self, mint: str):
        pool_id = await self.launchpad_core.find_launchpad_pool_by_mint(mint)
        if not pool_id:
            logging.error(f"{cc.RED}Pool ID not found for {mint} ✘")
            return

        asyncio.create_task(self.subscribe_state(str(pool_id), mint))
        asyncio.create_task(self.trade_handler(mint, pool_id))
        logging.info(f"Subscribed to {mint} | Pool ID: {pool_id} ✔")

    async def process_logs(self):
        while True:
            try:
                log, _ = await self.logs.get()
                res = log.get("params", {}).get("result", {}).get("value", {})
                if not res:
                    continue
                logs = res.get("logs", [])
                sig = self.dig_logs(logs, res.get("signature"))
                if sig:
                    meta = await self.get_swap_tx(sig)
                    if not meta:
                        continue
                    post_token_balances = meta.get("postTokenBalances", [])
                    for side in post_token_balances:
                        mint = side.get("mint", "")
                        if mint != str(WSOL_MINT):
                            if DEBUG_:
                                logging.info(f"{cc.ORANGE}New mint: {mint}")
                            await self.process_mint(mint)
                            break
            except asyncio.CancelledError:
                return
            except Exception as e:
                logging.error(f"Error processing logs: {e}")
                traceback.print_exc()
                await asyncio.sleep(3)

    async def trade_handler(self, mint: str, pool_id: str):
        try:
            inactivity_time = 0
            last_activity_time = time.time()
            last_price = 0.0
            buy_price = 0.0
            while mint not in self.sold:
                inactivity_time = time.time() - last_activity_time
                if inactivity_time > MAX_INACTIVITY_TIME:
                    if mint not in self.holdings:
                        logging.info(f"{cc.RED}Inactivity for {mint} | Inactivity time: {inactivity_time} seconds ✘")
                        self.sold.add(mint)
                        return

                open_price = self.mint_data[mint]['open_price']
                if open_price == 0.0:
                    await asyncio.sleep(1)
                    continue
                
                price = self.mint_data[mint]['current_price']
                if price != last_price:
                    last_price = price
                    last_activity_time = time.time()

                    if mint not in self.holdings:
                        if ENTER_LOW_PRICE:
                            enter_from_open = price > self.mint_data[mint]['low_price'] * FROM_OPEN
                        else:
                            enter_from_open = price > self.mint_data[mint]['open_price'] * FROM_OPEN

                        enter_min_buys = self.mint_data[mint]['stats']['buys'] > MIN_BUYS
                        if (enter_from_open and enter_min_buys):
                            logging.info(f"Entering {mint} | Price: {price:.10f} ✔")
                            await self.buy(mint, pool_id)
                            buy_price = self.mint_data[mint]['current_price']
                    
                    elif mint in self.holdings:
                        high_diff = ((self.mint_data[mint]['high_price'] - price) / self.mint_data[mint]['high_price']) * 100
                        if high_diff > MAX_LOSS_FROM_HIGH:
                            logging.info(f"{cc.RED}Peak loss for {mint} | High diff: {high_diff:.2f}% | Buy price: {buy_price:.10f} | Price: {price:.10f} ✘")
                            await self.sell(mint, pool_id)
                            return
                        elif buy_price > 0:
                            loss_in_pct = ((buy_price - price) / buy_price) * 100
                            if loss_in_pct > MAX_LOSS:
                                logging.info(f"{cc.RED}Max loss for {mint} | Loss: {loss_in_pct:.2f}% | Buy price: {buy_price:.10f} | Price: {price:.10f} ✘")
                                await self.sell(mint, pool_id)
                                return
                            elif price > (buy_price * TARGET_PROFIT):
                                profit_in_pct = ((price - buy_price) / buy_price) * 100
                                logging.info(f"{cc.LIGHT_GREEN}Target profit reached for {mint} | Profit: {profit_in_pct:.2f}% | Buy price: {buy_price:.10f} | Price: {price:.10f} ✔")
                                await self.sell(mint, pool_id)
                                return
                
                await asyncio.sleep(0.1)

        except Exception as e:
            logging.error(f"Error in trade_handler: {e}")
            traceback.print_exc()
            await asyncio.sleep(3)

    async def get_swap_tx(self, tx_id: str):
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [
                    tx_id,
                    {
                        "commitment": Confirmed,
                        "encoding": "json",
                        "maxSupportedTransactionVersion": 0
                    }
                ]
            }
            headers = {
                "Content-Type": "application/json"
            }

            async with self.session.post(HTTP_RPC, json=payload, headers=headers, timeout=10) as response:
                if response.status != 200:
                    logging.error(f"HTTP Error {response.status}: {await response.text()}")
                    raise Exception(f"HTTP Error {response.status}")

                data = await response.json()

                if data and data.get('result') is not None:
                    result = data['result']
                    meta = result.get("meta", {})
                    err = result.get("err", {})
                    if err:
                        return None
                    return meta
                else:
                    return None
        except Exception as e:
            logging.warning(f"Exception occurred: {e}")

    async def run(self):
        try:
            asyncio.create_task(self.subscribe("LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"))
            await asyncio.gather(
                self.process_updates(),
                self.process_logs(),
            )
        except asyncio.CancelledError:
            logging.info("Keyboard interrupt detected, exiting...")
            await self.close()
            await asyncio.sleep(1)

    async def close(self):
        await self.session.close()
        await self.client.close()

async def main():
    try:
        cr = XRay()
        await cr.run()
        await cr.close()
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt detected, exiting...")
        await cr.close()
        sys.exit(0)

def run():
    asyncio.run(main())

if __name__ == "__main__":
    asyncio.run(main())