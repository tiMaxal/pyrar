
// PayPal Payment plug-in JS

function paypal_startup() // {module}_startup() is a mandatory func in a JS payment module
{
	if ((gbl.config.payment)&&(gbl.config.payment.paypal)&&(gbl.config.payment.paypal.client_id))
		add_paypal_script(gbl.config.payment.paypal.client_id,gbl.config.currency.iso);

	payments["paypal"] = {
		"desc": "Pay by PayPal",
		"single": paypal_single_payment
		};
}


function add_paypal_script(client_id, currency) {
	let s = document.createElement('script');
	src = `https://www.paypal.com/sdk/js?client-id=${client_id}&enable-funding=venmo&currency=${currency}`;
	s.setAttribute("src", src );
	s.setAttribute("data-sdk-integration-source", "button-factory");
	document.body.appendChild( s );
}



function paypal_single_payment(description, amount)
{
	callApi("payments/single",(ok,reply)=> {
		if (!ok) return def_errMsg("Failed to create single use token",reply,"payment-whole");

		let x = "<table width=100%>"
		x += "<colgroup><col width=70%/><col/></colgroup>";
		x += "<tr><td align=center>Make payment by PayPal</td><td><span id='payment-button'></span></td></tr></table>";

		let e = document.getElementById("payment-whole");
		e.innerHTML = x;

		initPayPalButton(description, format_amount(amount,true), reply.token);
		},{ json:{ "provider":"paypal"}})
}


function test_single_paypal() // this is for debugging
{
	show_one_space("userSpace")
	elm.userSpace.innerHTML = "<div id='payment-whole'></div>";
	payments.paypal.single("Test Description",18.99);
}



function make_paypal_order(description, amount, custom_id)
{
	function paypal_amount(amount) { return { "currency_code": gbl.config.currency.iso, "value": format_amount(amount,true) }; }

	let ret_js = {
		purchase_units: [
			{
			"description": description,
			"custom_id": custom_id,
			"amount": paypal_amount(amount)
			}
		] };

	if ((ctx.orders)&&(ctx.orders.length > 0)) {
		let this_total = 0;
		let item_list = [];
		for(let order of ctx.orders) {
			let dom = domain_of(order.domain_id);
			this_total += order.price_paid;

			let yrs = `${order.num_years} yr`;
			if (order.num_years>1) yrs += "s";

			item_list.push({
				"name": `${order.order_type} '${dom.display_name}' for ${yrs}`,
				"quantity": 1,
				"unit_amount": paypal_amount(order.price_paid)
				});
			}
		ret_js.purchase_units[0].items = item_list;
		ret_js.purchase_units[0].amount.breakdown = {
			"item_total": paypal_amount(this_total),
			"discount": paypal_amount(ctx.user.acct_current_balance)
			};
		return ret_js;
		}

	ret_js.purchase_units[0].items = [ {
		"name": description,
		"quantity": 1,
		"unit_amount": paypal_amount(amount)
		} ];

	return ret_js;
}


function initPayPalButton(description, amount, custom_id) {
  paypal.Buttons({
		style: {
			shape: 'rect',
			color: 'gold',
			layout: 'horizontal',
			label: 'paypal',
		},

	createOrder: function(data, actions) {
		post_data = make_paypal_order(description, amount, custom_id);
		console.log(post_data);
		return actions.order.create(post_data);
	},

	onApprove: function(data, actions) {
	  return actions.order.capture().then(function(orderData) {
		// console.log(orderData);
		let e = document.getElementById("payment-whole");
		let x = '<center><h3>Thank you for your payment!</h3>'
		x += "Your payment will be processed when PayPal notifies us they have completed the transfer</center>";
		e.innerHTML = x;
	  });
	},

	onError: function(err) { 
		console.log(err);
		}

  }).render('#payment-button');
}