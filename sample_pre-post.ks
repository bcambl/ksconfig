# Include disk partitioning
%include /tmp/disk.part

%pre

# Change to tty1
exec < /dev/tty1 > /dev/tty1 2> /dev/tty1
chvt 1

#### Example-1: Include entire script within the kickstart file #
python << __EOF__
### <script here> ###
__EOF__
#### Example-1 End #


#### Example-2: Script include from seperate file via HTTP #
wget -q -O /tmp/<script> http://<url>/<script>
cat /tmp/<script> | python
#### Example-2 End #


#### Example-3: Script include from seperate file via NFS #
mkdir /tmp/ksconfig
mount -t nfs -o nolock,tcp <nfs_server_ip>:/<path_to>/ksconfig /tmp/ksconfig
cat /tmp/ksconfig/<prescript> | python
#### Example-3 End #

# Optional: Switch back to tty3 #
chvt 3
exec < /dev/tty3 > /dev/tty3 2> /dev/tty3

%end

#### nochroot is required for kspost.py:
%post --nochroot

# If using an NFS mount, you may execute the post script. Otherwise, see above
# %pre examples for include and wget methods.
cat /tmp/ksconfig/<postscript> | python

%end


#### Second Post section executes within chroot environment
%post

# Build Grub Configuration
grub2-mkconfig -o /boot/grub2/grub.cfg

%end
