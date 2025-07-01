import os, base64, asyncio
import struct
from typing import Tuple

from solana.rpc.types import TokenAccountOpts, TxOpts
from solana.rpc.commitment import Processed, Confirmed
from solana.rpc.async_api import AsyncClient

from solders.pubkey import Pubkey # type: ignore
from solders.keypair import Keypair # type: ignore 
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price # type: ignore
from solders.transaction import VersionedTransaction # type: ignore
from solders.message import MessageV0 # type: ignore
from spl.token.instructions import (
    create_associated_token_account,
    get_associated_token_address,
    initialize_account,
    InitializeAccountParams,
    CloseAccountParams, close_account
)
from solders.system_program import CreateAccountWithSeedParams, create_account_with_seed
from solders.instruction import Instruction, AccountMeta # type: ignore

try: from launchlab_core import RaydiumLaunchpadCore;
except: from .launchlab_core import RaydiumLaunchpadCore

def compute_unit_price_from_total_fee(
    total_lams: int,
    compute_units: int = 120_000
) -> int:
    lamports_per_cu = total_lams / float(compute_units)
    micro_lamports_per_cu = lamports_per_cu * 1_000_000
    return int(micro_lamports_per_cu)

RENT_EXEMPT     = 2039280
ACCOUNT_SIZE    = 165
SOL_DECIMALS    = 1e9
COMPUTE_UNITS   = 170_000
TOKEN_PROGRAM   = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")

BUY_EXACT_IN_DISCRIM = bytes([250, 234, 13, 123, 213, 156, 19, 236])
SELL_EXACT_IN_DISCRIM = bytes([149, 39, 222, 155, 211, 124, 152, 26])

class RaydiumLaunchpadSwap:
    def __init__(self, private_key: str | Keypair, client: AsyncClient):
        self.client = client
        self.signer = private_key if isinstance(private_key, Keypair) else Keypair.from_base58_string(private_key)
        self.core   = RaydiumLaunchpadCore(client)

    @staticmethod
    def convert_sol_to_tokens(sol: float, r_base: float, r_quote: float, fee_pct=1.0) -> float:
        eff = sol * (1 - fee_pct / 100)
        k   = r_base * r_quote
        new_base = k / (r_quote + eff)
        return round(r_base - new_base, 9)

    @staticmethod
    def convert_tokens_to_sol(tokens: float, r_base: float, r_quote: float, fee_pct=1.0) -> float:
        eff   = tokens * (1 - fee_pct / 100)
        k     = r_base * r_quote
        new_q = k / (r_base + eff)
        return round(r_quote - new_q, 9)

    async def execute_lp_buy_async(
        self,
        token_mint: str,
        sol_lamports: int,
        slippage_pct: float,
        pool_id: str | Pubkey | None = None,
        fee_micro_lamports: int = 1_000_000,
    ) -> Tuple[bool, str]:
        if pool_id is None:
            pool = await self.find_launchpad_pool_by_mint(token_mint)
            if not pool:
                raise RuntimeError("no Launchpad pool found")
            pool_id = pool
        pool_pk = pool_id if isinstance(pool_id, Pubkey) else Pubkey.from_string(pool_id)

        keys = await self.core.async_fetch_pool_keys(pool_pk)
        if keys is None:
            raise RuntimeError("cannot decode Launchpad pool")

        if keys.status == 2:
            return False, "Pool is migrated"

        out_mint = Pubkey.from_string(token_mint)
        resp = await self.client.get_token_accounts_by_owner(self.signer.pubkey(), TokenAccountOpts(mint=out_mint), Processed)
        if resp.value:
            user_ata = resp.value[0].pubkey
            create_ata_ix = None
        else:
            user_ata = get_associated_token_address(self.signer.pubkey(), out_mint)
            create_ata_ix = create_associated_token_account(
                self.signer.pubkey(), self.signer.pubkey(), out_mint
            )

        expected = self.core.calculate_constant_product_swap(keys, sol_lamports / SOL_DECIMALS)
        min_out  = int(expected * (1 - slippage_pct/100) * 10**keys.decimals_a)

        seed = base64.urlsafe_b64encode(os.urandom(12)).decode()
        temp_wsol = Pubkey.create_with_seed(self.signer.pubkey(), seed, TOKEN_PROGRAM)
        create_w_ix = create_account_with_seed(CreateAccountWithSeedParams(
            from_pubkey=self.signer.pubkey(),
            to_pubkey=temp_wsol,
            base=self.signer.pubkey(),
            seed=seed,
            lamports=RENT_EXEMPT + sol_lamports,
            space=ACCOUNT_SIZE,
            owner=TOKEN_PROGRAM,
        ))

        init_w_ix = initialize_account(
            InitializeAccountParams(
                program_id=TOKEN_PROGRAM,
                account=temp_wsol,
                mint=Pubkey.from_string("So11111111111111111111111111111111111111112"),
                owner=self.signer.pubkey(),
            )
        )

        metas = [
            AccountMeta(self.signer.pubkey(), True, False),
            AccountMeta(keys.authority, False, False),
            AccountMeta(keys.config_id, False, False),
            AccountMeta(keys.platform_id, False, False),
            AccountMeta(keys.pool_id, False, True),

            AccountMeta(user_ata, False, True),
            AccountMeta(temp_wsol, False, True),

            AccountMeta(keys.vault_a, False, True),
            AccountMeta(keys.vault_b, False, True),

            AccountMeta(keys.mint_a, False, False),
            AccountMeta(keys.mint_b, False, False),

            AccountMeta(TOKEN_PROGRAM, False, False),
            AccountMeta(TOKEN_PROGRAM, False, False),

            AccountMeta(keys.event_auth, False, False),
            AccountMeta(keys.program_id, False, False),
        ]
        data = (
            BUY_EXACT_IN_DISCRIM
            + struct.pack("<Q", sol_lamports)
            + struct.pack("<Q", min_out)
            + struct.pack("<Q", 0)   # shareFeeRate = 0
        )
        swap_ix = Instruction(keys.program_id, data, metas)
        fee_micro_lamports = compute_unit_price_from_total_fee(fee_micro_lamports, COMPUTE_UNITS)
        ixs = [
            set_compute_unit_limit(COMPUTE_UNITS),
            set_compute_unit_price(fee_micro_lamports),
            create_w_ix, init_w_ix,
        ]
        if create_ata_ix:
            ixs.append(create_ata_ix)
        ixs.append(swap_ix)
        ixs.append(close_account(CloseAccountParams(
            program_id=TOKEN_PROGRAM,
            account=temp_wsol,
            dest=self.signer.pubkey(),
            owner=self.signer.pubkey(),
        )))

        blockhash = (await self.client.get_latest_blockhash()).value.blockhash
        msg      = MessageV0.try_compile(self.signer.pubkey(), ixs, [], blockhash)
        tx       = VersionedTransaction(msg, [self.signer])
        sig_resp = await self.client.send_transaction(tx, opts=TxOpts(skip_preflight=True, max_retries=0))
        ok       = await self._await_confirm(sig_resp.value)
        return ok, sig_resp.value

    async def execute_lp_sell_async(
        self,
        token_mint: str,
        sell_pct: float = 100,
        slippage_pct: float = 5,
        pool_id: str | Pubkey | None = None,
        fee_micro_lamports: int = 1_000_000,
    ) -> Tuple[bool, str]:
        if pool_id is None:
            pool = await self.core.find_launchpad_pool_by_mint(token_mint)
            if not pool:
                raise RuntimeError("no Launchpad pool found")
            pool_id = pool
        pool_pk = pool_id if isinstance(pool_id, Pubkey) else Pubkey.from_string(pool_id)

        keys = await self.core.async_fetch_pool_keys(pool_pk)
        if keys is None:
            raise RuntimeError("cannot decode Launchpad pool")
        
        if keys.status == 2:
            return False, "Pool is migrated"

        token_pk = Pubkey.from_string(token_mint)
        bal_resp = await self.client.get_token_accounts_by_owner_json_parsed(
            self.signer.pubkey(), TokenAccountOpts(mint=token_pk), Processed
        )
        if not bal_resp.value:
            raise RuntimeError("no token balance to sell")

        token_balance = float(bal_resp.value[0].account.data.parsed["info"]["tokenAmount"]["uiAmount"] or 0)
        
        user_ata = bal_resp.value[0].pubkey
        
        if token_balance <= 0:
            raise RuntimeError("insufficient token balance")

        sell_amount = token_balance * (sell_pct / 100)
        if sell_amount <= 0:
            raise RuntimeError("sell amount too small")

        expected_sol = self.core.calculate_constant_product_sell(keys, sell_amount)
        min_sol_out = int(expected_sol * (1 - slippage_pct/100) * SOL_DECIMALS)
        token_amount_raw = int(sell_amount * 10**keys.decimals_a)
        
        seed = base64.urlsafe_b64encode(os.urandom(12)).decode()
        temp_wsol = Pubkey.create_with_seed(self.signer.pubkey(), seed, TOKEN_PROGRAM)
        create_w_ix = create_account_with_seed(CreateAccountWithSeedParams(
            from_pubkey=self.signer.pubkey(),
            to_pubkey=temp_wsol,
            base=self.signer.pubkey(),
            seed=seed,
            lamports=RENT_EXEMPT,
            space=ACCOUNT_SIZE,
            owner=TOKEN_PROGRAM,
        ))

        init_w_ix = initialize_account(
            InitializeAccountParams(
                program_id=TOKEN_PROGRAM,
                account=temp_wsol,
                mint=Pubkey.from_string("So11111111111111111111111111111111111111112"),
                owner=self.signer.pubkey(),
            )
        )

        metas = [
            AccountMeta(self.signer.pubkey(), True, False),
            AccountMeta(keys.authority, False, False),
            AccountMeta(keys.config_id, False, False),
            AccountMeta(keys.platform_id, False, False),
            AccountMeta(keys.pool_id, False, True),

            AccountMeta(user_ata, False, True),
            AccountMeta(temp_wsol, False, True),

            AccountMeta(keys.vault_a, False, True),
            AccountMeta(keys.vault_b, False, True),

            AccountMeta(keys.mint_a, False, False),
            AccountMeta(keys.mint_b, False, False),

            AccountMeta(TOKEN_PROGRAM, False, False),
            AccountMeta(TOKEN_PROGRAM, False, False),

            AccountMeta(keys.event_auth, False, False),
            AccountMeta(keys.program_id, False, False),
        ]
        data = (
            SELL_EXACT_IN_DISCRIM
            + struct.pack("<Q", token_amount_raw)
            + struct.pack("<Q", min_sol_out)
            + struct.pack("<Q", 0)   # shareFeeRate = 0
        )
        sell_ix = Instruction(keys.program_id, data, metas)
        fee_micro_lamports = compute_unit_price_from_total_fee(fee_micro_lamports, COMPUTE_UNITS)

        ixs = [
            set_compute_unit_limit(COMPUTE_UNITS),
            set_compute_unit_price(fee_micro_lamports),
            create_w_ix, init_w_ix,
            sell_ix,
            close_account(CloseAccountParams(
                program_id=TOKEN_PROGRAM,
                account=temp_wsol,
                dest=self.signer.pubkey(),
                owner=self.signer.pubkey(),
            ))
        ]

        blockhash = (await self.client.get_latest_blockhash()).value.blockhash
        msg      = MessageV0.try_compile(self.signer.pubkey(), ixs, [], blockhash)
        tx       = VersionedTransaction(msg, [self.signer])
        sig_resp = await self.client.send_transaction(tx, opts=TxOpts(skip_preflight=True, max_retries=0))
        ok       = await self._await_confirm(sig_resp.value)
        return ok, sig_resp.value

    async def _await_confirm(self, sig: str, tries=3, delay=2):
        for _ in range(tries):
            res = await self.client.get_transaction(sig, commitment=Confirmed, max_supported_transaction_version=0)
            if res.value and res.value.transaction.meta.err is None:
                return True
            await asyncio.sleep(delay)
        return False

    async def close(self):
        await self.client.close()