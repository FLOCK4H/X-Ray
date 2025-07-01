<div align="center">
  
  <img src="https://github.com/user-attachments/assets/f5d00420-24b2-48ce-a1e7-cdfa0d643030" width=256 />
  
</div>

# X-Ray

Optimized for speed, free, and open-source project for **trading tokens released on Raydium Launchpad.** The swaps are being made using custom `launchlab` module, **there's no reliance on Jupyter or any other router** - Transactions are built on your machine and then sent directly to your Solana RPC node.

## Features

- Real-time token monitor
- Configurable trades
- Fast transactions & High transaction landing rate

## Setup

### 1. Download this Git repo

```
$ git clone https://github.com/FLOCK4H/X-Ray
```

### 2. Install the X-Ray (optional)

```
$ cd X-Ray
$ pip install .
```

### 3. Configure settings

> [!NOTE]
> Settings should be in the `.env` file and located in your current working directory when running the bot.</h5>

```
HTTP_RPC = "https://mainnet.helius-rpc.com/?api-key=" # can be any other standard solana rpc node provider
WS_RPC_URL = "wss://mainnet.helius-rpc.com/?api-key=" # can be any other standard solana rpc node provider
KEYPAIR = "" # aka private key, in base58 format - Phantom format
BUY_AMOUNT = 0.001
FEE = 0.00004 # RAYDIUM IS A VERY VOLATILE MARKET, PLEASE SET HIGHER FEE OR TXNS MAY FAIL DUE TO SLIPPAGE
MIN_BUYS = 10 # mininum buys before buying a token
FROM_OPEN = 2.5 # minimum price from open/ low to enter token, e.g. lowest price is always 0.0000000280 so times 2.5 is ~0.0000000700
ENTER_LOW_PRICE = True # enter based on low price instead of open price
SLIPPAGE_PCT = 30 # slippage percentage

# selling:
MAX_LOSS_FROM_HIGH = 30 # max loss from high price
MAX_INACTIVITY_TIME = 20 # max inactivity time
MAX_LOSS = 15 # max loss from buy price
TARGET_PROFIT = 2.5 # target profit from buy price

DEBUG_ = True # enables debug logs
```

### 4. Run

a) **You have installed X-Ray**

<h5>Simply run the command below</h5>

```
$ x-ray
```

b) **You haven't installed**

<h5>Navigate to `src/x_ray` and ensure the `.env` file is there. Then run the `main.py`.</h5>

```
$ cd src/x_ray
$ ls -a
$ python main.py
```

![image](https://github.com/user-attachments/assets/d6700609-c402-4bd9-b45c-8015bf5a87d7)

## Contact

TG Priv: @dubskii420

TG Group: https://t.me/flock4hcave

Discord Group: https://discord.gg/thREUECv2a

Tip Wallet: FL4CKfetEWBMXFs15ZAz4peyGbCuzVaoszRKcoVt3WfC
