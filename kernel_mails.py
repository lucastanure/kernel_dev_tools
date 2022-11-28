lei q -I https://lore.kernel.org/all/ -F mboxrd -o ~/Mail/rockchip  --threads --dedupe=mid '(dfn:drivers/pci/controller/dwc/pcie-dw-rockchip.c) AND rt:1.month.ago..'

b4 am -o - <message-id> | git am


https://josefbacik.github.io/kernel/2021/10/18/lei-and-b4.html
https://people.kernel.org/monsieuricon/lore-lei-part-1-getting-started
https://public-inbox.org/git/20220323133253.55i4sy5fs2zy5ocj@meerkat.local/T/
https://people.kernel.org/monsieuricon/introducing-b4-and-patch-attestation



lei q -I https://lore.kernel.org/all/ -f mboxrd -o ~/Mail/rockchip  --threads --dedupe=mid \
    '(dfn:drivers/pci/controller/dwc/pcie-dw-rockchip.c OR \
      dfn:arch/arm64/boot/dts/rockchip/rk3588s-pinctrl.dtsi OR \
      dfn:arch/arm64/boot/dts/rockchip/rk3588s.dtsi OR \
      dfn:arch/arm64/boot/dts/rockchip/rk3588.dtsi OR \
      dfn:arch/arm64/boot/dts/rockchip/rk3588-pinctrl.dtsi OR \
      dfn:arch/arm64/boot/dts/rockchip/rk3588s-rock-5a.dts OR \
      dfn:arch/arm64/boot/dts/rockchip/rk3588-rock-5b.dts OR \
      dfn:drivers/phy/rockchip/phy-rockchip-naneng-combphy.c OR \
      dfn:arch/arm64/boot/dts/rockchip/rk3588s-rk806-single.dtsi OR \
      dfn:drivers/regulator/rk808-regulator.c OR \
      dfn:drivers/mfd/rk8xx-spi.c \
      ) AND rt:3.month.ago..'