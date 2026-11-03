# Block direct web access to the application folder (code, database, settings).
# The site itself is served by Passenger through the domain's root .htaccess.
Require all denied
<IfModule !mod_authz_core.c>
  Order allow,deny
  Deny from all
</IfModule>
