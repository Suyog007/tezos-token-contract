import smartpy as sp
FA2 = sp.io.import_script_from_url("https://smartpy.io/templates/fa2_lib.py")

class NftWithAdmin(FA2.Admin, FA2.Fa2Nft, FA2.OnchainviewBalanceOf, 
FA2.WithdrawMutez):
    def __init__(self, admin, **kwargs):
        FA2.Fa2Nft.__init__(self, **kwargs)
        FA2.Admin.__init__(self, admin)
        self.update_initial_storage(
            token_price = sp.mutez(0),
            whitelist = sp.set([], t = sp.TAddress)
        )
    
    @sp.entry_point
    def add_whitelist(self, params):
        """Add whitelist address through admin."""
        sp.verify(self.is_administrator(sp.sender), "Only Admin can whitelist the address.")
        sp.for x in params:
            sp.verify(~self.data.whitelist.contains(x),
            message="Already Whitelisted")
            self.data.whitelist.add(x)
            # event log emitted
            sp.emit(x)
    
    @sp.entry_point
    def set_token_price(self, price_in_mutez):
        """Sets token price for NFT."""
        sp.verify(self.is_administrator(sp.sender), "Only Admin can set the nft price.")
        self.data.token_price = price_in_mutez

    @sp.entry_point(check_no_incoming_transfer = False)
    def mint(self, batch):
        """ A very simple implementation of the mint entry point"""
        sp.verify(sp.amount == self.data.token_price, "Invalid Price")
        sp.verify(self.data.whitelist.contains(sp.sender), "Address not whitelisted.")
        sp.set_type(
            batch,
            sp.TList(
                sp.TRecord(
                    to_=sp.TAddress,
                    metadata=sp.TMap(sp.TString, sp.TBytes),
                ).layout(("to_", "metadata"))
            ),
        )
        with sp.for_("action", batch) as action:
            token_id = sp.compute(self.data.last_token_id)
            metadata = sp.record(token_id=token_id, 
token_info=action.metadata)
            self.data.token_metadata[token_id] = metadata
            self.data.ledger[token_id] = action.to_
            self.data.last_token_id += 1
    
    @sp.entry_point
    def burn(self, batch):
        """Users can burn tokens if they have the transfer policy 
        permission.
        Burning an nft destroys its metadata.
        """
        sp.set_type(
            batch,
            sp.TList(
                sp.TRecord(
                    from_=sp.TAddress,
                    token_id=sp.TNat,
                    amount=sp.TNat,
                ).layout(("from_", ("token_id", "amount")))
            ),
        )
        sp.verify(self.policy.supports_transfer, "FA2_TX_DENIED")
        with sp.for_("action", batch) as action:
            sp.verify(self.is_defined(action.token_id), "FA2_TOKEN_UNDEFINED")
            self.policy.check_tx_transfer_permissions(
                self, action.from_, action.from_, action.token_id
            )
            with sp.if_(action.amount > 0):
                sp.verify(
                    (action.amount == sp.nat(1))
                    & (self.data.ledger[action.token_id] == action.from_),
                    message="FA2_INSUFFICIENT_BALANCE",
                )
                # Burn the token
                del self.data.ledger[action.token_id]
                del self.data.token_metadata[action.token_id]

    @sp.onchain_view()
    def total_supply(self, params):
        """Return the total number of tokens for the given `token_id`."""
        sp.verify(self.is_defined(params.token_id), "FA2_TOKEN_UNDEFINED")
        sp.result(sp.set_type_expr(self.supply_(params.token_id), sp.TNat))

@sp.add_test(name="NFT with mint and burn")
def test():
    sc = sp.test_scenario()
    admin = sp.address("tz1euHP1ntD4r3rv8BsE5pXpTRBnUFu69wYP")
    alice = sp.address("tz1g3pJZPifxhN49ukCZjdEQtyWgX2ERdfqP")
    token_price = sp.mutez(1000000)
    
    # deploy a contract
    c1 = NftWithAdmin(
        admin = admin,
        metadata = sp.utils.metadata_of_url("https://example2.com"),
        policy = FA2.PauseTransfer()
        )
    sc += c1

    sc.h2("Set token price")
    c1.set_token_price(token_price).run(sender=admin)
    sc.verify(c1.data.token_price == token_price)

    sc.h2("whitelist the admin address")
    c1.add_whitelist([admin]
    ).run(sender = admin)
    sc.verify_equal(c1.data.whitelist, sp.set([admin]))

    sc.h2("whitelist the alice address")
    c1.add_whitelist([alice]
    ).run(sender = admin)
    sc.verify_equal(c1.data.whitelist, sp.set([admin, alice]))

    sc.h2("Whitelist called by alice instead of admin")
    c1.add_whitelist([alice]
    ).run(sender = alice, valid = False, exception ="Only Admin can whitelist the address." )
    
    sc.h2("Mint a token without sending tez")
    c1.mint([
    sp.record(
    to_ = admin, metadata = sp.map({
    "test":sp.utils.bytes_of_string("ipfs//test_uri")}))
    ]
    ).run(sender = admin, valid = False, exception = "Invalid Price")

    # last token ID before minting
    sc.verify_equal(c1.data.last_token_id, 0)
    
    sc.h2("Mint a token to admin address")
    c1.mint([
    sp.record(
    to_ = admin, metadata = sp.map({
    "test":sp.utils.bytes_of_string("ipfs//test_uri")}))
    ]
    ).run(sender = admin, amount = token_price)
    sc.verify_equal(c1.data.last_token_id, 1)
    sc.verify_equal(c1.data.ledger[0], admin)
    sc.verify_equal(c1.data.ledger.contains(0), True)

    sc.h2("Mint a token to alice address")
    c1.mint([
    sp.record(
    to_ = alice, metadata = sp.map({
    "test":sp.utils.bytes_of_string("ipfs//test_uri")}))
    ]
    ).run(sender = alice, amount = token_price)
    sc.verify_equal(c1.data.last_token_id, 2)
    sc.verify_equal(c1.data.ledger[1], alice)

    sc.h2("Transfers a token")
    c1.transfer([
    sp.record(
    from_ = admin,
    txs = [ sp.record( amount = 1, token_id = 0, to_ = alice)])
    ]
    ).run(sender = admin)
    sc.verify_equal(c1.data.last_token_id, 2)
    sc.verify_equal(c1.data.ledger[0], alice)
    sc.verify_equal(c1.data.ledger[1], alice)

    sc.h2("Burn a token")
    c1.burn([
    sp.record(
    amount = 1, token_id = 0, from_ = alice)
    ]
    ).run(sender = alice)
    sc.verify_equal(c1.data.ledger.contains(0), False)

    sc.h2("Pause the transfer")
    c1.set_pause(True).run(sender = admin)

    sc.h2("Transfers a token during pause")
    c1.transfer([
    sp.record(
    from_ = alice,
    txs = [ sp.record( amount = 1, token_id = 1, to_ = admin)])
    ]
    ).run(sender = alice, valid = False, exception = ('FA2_TX_DENIED', 
'FA2_PAUSED'))

