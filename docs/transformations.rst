HTML transformer
================

.. testsetup:: *

    import emails
    import io

Message HTML body usually should be modified before sent.

Base transformations, such as css inlining can be made by `Message.transform` method:

.. doctest::

    >>> message = emails.Message(html="<style>h1{color:red}</style><h1>Hello world!</h1>")
    >>> message.transform()
    >>> message.html  # doctest: +ELLIPSIS
    '<html><head>...</head><body><h1 style="color:red">Hello world!</h1></body></html>'

`Message.transform` can take some arguments with speaken names `css_inline`, `remove_unsafe_tags`,
`make_links_absolute`, `set_content_type_meta`, `update_stylesheet`, `images_inline`.

More specific transformation can be made via `transformer` property.

Example of custom link transformations:

.. doctest::

    >>> message = emails.Message(html="<img src='promo.png'>")
    >>> message.transformer.apply_to_images(func=lambda src, **kw: 'http://mycompany.tld/images/'+src)
    >>> message.transformer.save()
    >>> message.html
    '<html><body><img src="http://mycompany.tld/images/promo.png"/></body></html>'

Example of customized making images inline:

.. doctest::

    >>> message = emails.Message(html="<img src='promo.png'>")
    >>> message.attach(filename='promo.png', data=io.BytesIO(b'PNG_DATA'))
    >>> message.attachments['promo.png'].is_inline = True
    >>> _ = message.transformer.synchronize_inline_images()
    >>> message.transformer.save()
    >>> message.html
    '<html><body><img src="cid:promo.png"/></body></html>'


Remote resources and untrusted HTML
-----------------------------------

`Message.transform` and the loaders fetch external stylesheets (``<link rel="stylesheet">``)
and images (``<img src>``) referenced from the HTML.
To protect against SSRF when HTML comes from untrusted users, every url
(including redirect targets) is checked before it is fetched:
only ``http`` and ``https`` urls whose host resolves to a public IP address are allowed.
Fetching a url that points to a loopback, private, link-local or otherwise
non-public address raises :exc:`emails.UnsafeURLError`. TLS certificates are verified.
CSS ``@import`` rules are never fetched.

If your HTML comes only from trusted sources and you need to load resources
from internal hosts (for example, a local development server), replace the validator:

.. code-block:: python

    import emails.utils

    # disable checks completely
    emails.utils.url_validator = None

    # or allow a specific internal host
    def my_validator(url):
        if not url.startswith('http://assets.internal/'):
            emails.utils.default_url_validator(url)

    emails.utils.url_validator = my_validator

The check is a mitigation, not a complete SSRF protection. Known limitations:

* **DNS rebinding.** The validator resolves the host name separately from the actual
  connection, so a host that resolves to a public address during the check may resolve
  to an internal one when connecting.
* **Proxies.** Requests are made with ``requests`` defaults, so proxies from environment
  variables (``HTTP_PROXY``, ``HTTPS_PROXY``, ``ALL_PROXY``) are used. A proxy resolves
  and connects to the destination itself and may reach addresses the validator would reject.
* **Ambient credentials.** Credentials from ``~/.netrc`` (or ``NETRC``) are sent to
  the matching hosts, as ``requests`` does by default.

If you render HTML from untrusted users, also restrict outgoing traffic of the process
at the network level (firewall or an egress proxy that enforces destination filtering),
and do not keep ``.netrc`` credentials or proxy settings with access to internal
services in that environment.


Loaders
-------

python-emails ships with couple of loaders.

Load message from url:

.. code-block:: python

    import emails.loader
    message = emails.loader.from_url(url="http://xxx.github.io/newsletter/2015-08-14/index.html")


Load from zipfile or directory:

.. code-block:: python

    message = emails.loader.from_zip(open('design_pack.zip', 'rb'))
    message = emails.loader.from_directory('/home/user/design_pack')

Zipfile and directory loaders require at least one html file (with "html" extension).

Load message from `.eml` file (experimental):

.. code-block:: python

    message = emails.loader.from_rfc822(open('message.eml').read())
